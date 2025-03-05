from flask import Flask, send_file, render_template, request, jsonify, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler
import os
import random
import json
from threading import Lock
from datetime import datetime, timedelta
import hashlib
from werkzeug.http import http_date
import mimetypes

def parse_cron(exp: str) -> dict:
    """解析cron表达式为字典参数"""
    fields = exp.strip().split()
    return {
        'minute': fields[0],
        'hour': fields[1],
        'day': fields[2],
        'month': fields[3],
        'day_of_week': fields[4]
    }

app = Flask(__name__)
# 使用当前目录作为基础目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_FOLDER = os.getenv('IMAGE_FOLDER', os.path.join(BASE_DIR, 'images'))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

print(f"应用程序配置信息:")
print(f"BASE_DIR: {BASE_DIR}")
print(f"IMAGE_FOLDER: {IMAGE_FOLDER}")
print(f"CONFIG_FILE: {CONFIG_FILE}")

# 确保必要的目录存在
os.makedirs(IMAGE_FOLDER, exist_ok=True)

CURRENT_IMAGE = {"path": None}
lock = Lock()

# 初始化配置
try:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cron_exp = json.load(f).get('cron', '0 0 * * *')
    else:
        cron_exp = '0 0 * * *'
        # 创建默认配置文件
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'cron': cron_exp}, f)
except Exception as e:
    print(f"配置加载失败: {str(e)}")
    cron_exp = '0 0 * * *'

def get_file_hash(filepath):
    """计算文件的MD5哈希值"""
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hasher.update(chunk)
    return hasher.hexdigest()

def get_file_info(filepath):
    """获取文件信息"""
    stat = os.stat(filepath)
    return {
        'size': stat.st_size,
        'mtime': stat.st_mtime,
        'etag': f'"{get_file_hash(filepath)}"'
    }

# 定时任务逻辑
def scheduled_refresh():
    with lock:
        try:
            start_time = datetime.now()
            print(f"[{start_time}] 开始刷新图片...")

            # 检查目录是否存在
            if not os.path.exists(IMAGE_FOLDER):
                print(f"图片目录不存在: {IMAGE_FOLDER}")
                return

            # 获取图片列表（添加文件大小限制）
            print(f"扫描目录: {IMAGE_FOLDER}")
            all_files = os.listdir(IMAGE_FOLDER)
            print(f"目录中的所有文件: {all_files}")
            
            images = []
            for f in all_files:
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                    file_path = os.path.join(IMAGE_FOLDER, f)
                    try:
                        file_size = os.path.getsize(file_path) / (1024 * 1024)  # 转换为MB
                        print(f"检查文件: {f} (大小: {file_size:.1f}MB)")
                        if file_size <= 50:  # 限制文件大小不超过50MB
                            images.append(f)
                            print(f"添加文件到列表: {f}")
                        else:
                            print(f"跳过大文件 {f} ({file_size:.1f}MB)")
                    except Exception as e:
                        print(f"读取文件 {f} 时出错: {str(e)}")
            
            # 检查是否有图片
            if not images:
                print(f"没有找到合适的图片文件")
                print(f"支持的格式: .png, .jpg, .jpeg, .gif, .bmp")
                return
            
            print(f"可用图片列表: {images}")
            
            # 选择并设置图片
            selected_image = random.choice(images)
            image_path = os.path.join(IMAGE_FOLDER, selected_image)
            print(f"选中图片: {selected_image}")
            
            # 验证文件是否可访问
            if not os.path.isfile(image_path):
                print(f"选中的图片文件不存在: {image_path}")
                return
                
            try:
                # 测试文件是否可读
                with open(image_path, 'rb') as f:
                    f.read(1)
                print(f"文件可以正常读取: {image_path}")
            except Exception as e:
                print(f"文件无法读取: {image_path}")
                print(f"错误信息: {str(e)}")
                return
                
            CURRENT_IMAGE['path'] = image_path
            CURRENT_IMAGE['update_time'] = start_time
            CURRENT_IMAGE['info'] = get_file_info(image_path)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            file_size = os.path.getsize(image_path) / (1024 * 1024)  # MB
            print(f"[{end_time}] 图片已切换至: {CURRENT_IMAGE['path']} ({file_size:.1f}MB)")
            print(f"刷新耗时: {duration:.2f}秒")
            
        except Exception as e:
            print(f"更新图片时发生错误: {str(e)}")
            import traceback
            print(traceback.format_exc())

# 初始化调度器
scheduler = BackgroundScheduler(daemon=True, timezone='Asia/Shanghai')
scheduler.start()  # 先启动调度器

# 解析当前的cron表达式
try:
    cron_dict = parse_cron(cron_exp)
    job = scheduler.add_job(scheduled_refresh, 'cron', id='refresh_task', **cron_dict)
    print(f"已设置定时任务: {cron_exp}")
    if job and job.next_run_time:
        print(f"下次执行时间: {job.next_run_time}")
except Exception as e:
    print(f"设置定时任务失败，使用默认值: {str(e)}")
    job = scheduler.add_job(scheduled_refresh, 'cron', id='refresh_task', minute='*/1')  # 默认每1分钟执行一次
    if job and job.next_run_time:
        print(f"已设置默认定时任务，下次执行时间: {job.next_run_time}")

# 路由
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/image')
def get_image():
    try:
        # 如果没有当前图片，尝试刷新
        if not CURRENT_IMAGE.get('path'):
            scheduled_refresh()
            
        # 再次检查是否有可用图片
        if not CURRENT_IMAGE.get('path'):
            return jsonify({"error": "没有可用的图片"}), 404
            
        # 验证文件是否存在且可访问
        if not os.path.isfile(CURRENT_IMAGE['path']):
            return jsonify({"error": f"图片文件不存在: {CURRENT_IMAGE['path']}"}), 404

        # 获取文件信息
        file_info = get_file_info(CURRENT_IMAGE['path'])
        
        # 检查客户端缓存
        if_none_match = request.headers.get('If-None-Match')
        if if_none_match and if_none_match == file_info['etag']:
            return '', 304
        
        # 设置响应头
        headers = {
            'Cache-Control': 'public, max-age=60',  # 1分钟缓存
            'ETag': file_info['etag'],
            'Last-Modified': http_date(file_info['mtime']),
            'Content-Type': mimetypes.guess_type(CURRENT_IMAGE['path'])[0],
            'Content-Length': str(file_info['size'])
        }
        
        # 使用send_from_directory进行流式传输
        directory = os.path.dirname(CURRENT_IMAGE['path'])
        filename = os.path.basename(CURRENT_IMAGE['path'])
        return send_from_directory(
            directory, 
            filename, 
            conditional=True,
            download_name=filename,
            as_attachment=False,
            mimetype=headers['Content-Type']
        )
        
    except Exception as e:
        error_msg = f"获取图片时发生错误: {str(e)}"
        print(error_msg)
        return jsonify({"error": error_msg}), 500

@app.route('/refresh', methods=['POST'])
def refresh_image():
    """手动刷新图片的API端点"""
    scheduled_refresh()
    return jsonify({"status": "success"})

@app.route('/get-schedule', methods=['GET'])
def get_schedule():
    """获取当前的cron设置和下次执行时间"""
    try:
        job = scheduler.get_job('refresh_task')
        next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job and job.next_run_time else 'unknown'
        current_image = os.path.basename(CURRENT_IMAGE['path']) if CURRENT_IMAGE.get('path') else None
        update_time = CURRENT_IMAGE.get('update_time', None)
        update_time_str = update_time.strftime('%Y-%m-%d %H:%M:%S') if update_time else 'unknown'
        
        return jsonify({
            "cron": cron_exp,
            "next_run": next_run,
            "current_image": current_image,
            "last_update": update_time_str
        })
    except Exception as e:
        print(f"获取调度信息失败: {str(e)}")
        return jsonify({
            "cron": cron_exp,
            "next_run": "unknown",
            "current_image": None,
            "last_update": "unknown",
            "error": str(e)
        })

@app.route('/save-schedule', methods=['POST'])
def save_schedule():
    try:
        new_cron = request.json.get('cron')
        # 基本格式验证
        if len(new_cron.split()) != 5:
            raise ValueError("Cron表达式需要5个字段")
        
        # 验证并解析cron表达式
        cron_dict = parse_cron(new_cron)
        
        # 更新调度任务
        try:
            job = scheduler.reschedule_job('refresh_task', trigger='cron', **cron_dict)
            if job and job.next_run_time:
                print(f"成功更新定时任务: {new_cron}")
                print(f"下次执行时间: {job.next_run_time}")
            else:
                raise Exception("无法获取下次执行时间")
        except Exception as e:
            raise Exception(f"更新定时任务失败: {str(e)}")
        
        # 保存到配置文件
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({'cron': new_cron}, f, ensure_ascii=False, indent=2)
            print(f"配置已保存到: {CONFIG_FILE}")
        except Exception as e:
            raise Exception(f"配置文件保存失败: {str(e)}")
        
        global cron_exp
        cron_exp = new_cron
        
        # 立即触发一次刷新
        scheduled_refresh()
        
        return jsonify({
            "status": "success",
            "next_run": job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job and job.next_run_time else 'unknown'
        })
    
    except Exception as e:
        error_msg = str(e)
        print(f"保存调度设置失败: {error_msg}")
        return jsonify({"error": error_msg}), 400

@app.route('/img/today')
@app.route('/img/today.<format>')
def get_today_image(format=None):
    """提供一个固定的图片访问地址，支持任意图片格式"""
    try:
        # 如果没有当前图片，尝试刷新
        if not CURRENT_IMAGE.get('path'):
            scheduled_refresh()
            
        # 再次检查是否有可用图片
        if not CURRENT_IMAGE.get('path'):
            return jsonify({"error": "没有可用的图片"}), 404
            
        # 验证文件是否存在且可访问
        if not os.path.isfile(CURRENT_IMAGE['path']):
            return jsonify({"error": f"图片文件不存在: {CURRENT_IMAGE['path']}"}), 404

        # 获取文件信息
        file_info = get_file_info(CURRENT_IMAGE['path'])
        
        # 获取更新时间作为版本号
        version = str(int(CURRENT_IMAGE.get('update_time', datetime.now()).timestamp()))
        
        # 获取实际的文件MIME类型
        actual_mime_type = mimetypes.guess_type(CURRENT_IMAGE['path'])[0]
        
        # 设置响应头，强制浏览器定期刷新
        response = send_file(
            CURRENT_IMAGE['path'],
            mimetype=actual_mime_type,
            conditional=True
        )
        
        # 添加缓存控制头
        response.headers['Cache-Control'] = 'no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Version'] = version  # 添加版本号
        response.headers['X-Original-Format'] = os.path.splitext(CURRENT_IMAGE['path'])[1][1:]  # 添加原始格式信息
        
        # 添加Last-Modified和ETag
        response.headers['Last-Modified'] = http_date(file_info['mtime'])
        response.headers['ETag'] = f'"{version}"'  # 使用版本号作为ETag
        
        return response
        
    except Exception as e:
        error_msg = f"获取图片时发生错误: {str(e)}"
        print(error_msg)
        return jsonify({"error": error_msg}), 500

if __name__ == '__main__':
    print("启动应用程序...")
    scheduled_refresh()  # 启动时立即加载
    app.run(host='0.0.0.0', port=5000)