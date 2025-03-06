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
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

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

def translate_cron(exp: str) -> str:
    """将cron表达式翻译成人类可读的文本"""
    try:
        fields = exp.strip().split()
        if len(fields) != 5:
            return "无效的cron表达式"
            
        minute, hour, day, month, week = fields
        
        # 处理分钟
        minute_desc = ""
        if minute == "*":
            minute_desc = "每分钟"
        elif minute.startswith('*/'):
            minutes = minute[2:]
            minute_desc = f"每{minutes}分钟"
        elif minute.isdigit():
            minute_desc = f"第{minute}分钟"
            
        # 处理小时
        hour_desc = ""
        if hour == "*":
            if minute == "0":
                hour_desc = "每小时整点"
            else:
                hour_desc = "每小时"
        elif hour.startswith('*/'):
            hours = hour[2:]
            if minute == "0":
                hour_desc = f"每{hours}小时整点"
            else:
                hour_desc = f"每{hours}小时的第{minute}分钟"
        elif hour.isdigit():
            hour_int = int(hour)
            if hour_int < 12:
                hour_desc = f"上午{hour_int}点"
            elif hour_int == 12:
                hour_desc = "中午12点"
            else:
                hour_desc = f"下午{hour_int-12}点"
                
        # 处理星期
        week_desc = ""
        if week != "*":
            week_map = {
                "0": "周日",
                "6": "周六",
                "1": "周一",
                "2": "周二",
                "3": "周三",
                "4": "周四",
                "5": "周五",
                "1-5": "工作日"
            }
            if week in week_map:
                week_desc = f"在{week_map[week]}"
            elif week.startswith('*/'):
                weeks = week[2:]
                week_desc = f"每{weeks}天"
                
        # 处理月份
        month_desc = ""
        if month != "*":
            if month.isdigit():
                month_desc = f"{month}月"
            elif month.startswith('*/'):
                months = month[2:]
                month_desc = f"每{months}个月"
                
        # 处理日期
        day_desc = ""
        if day != "*":
            if day.isdigit():
                day_desc = f"{day}日"
            elif day.startswith('*/'):
                days = day[2:]
                day_desc = f"每{days}天"
                
        # 组合描述
        if minute == "0" and hour != "*":
            # 对于整点的特殊处理
            if hour.isdigit():
                desc = f"{week_desc} {month_desc} {day_desc} {hour_desc}".strip()
            else:
                desc = f"{week_desc} {month_desc} {day_desc} {hour_desc}".strip()
        else:
            if minute == "*" and hour == "*":
                desc = "每分钟"
            elif minute.startswith('*/') and hour == '*':
                desc = minute_desc
            else:
                desc = f"{week_desc} {month_desc} {day_desc} {hour_desc} {minute_desc}".strip()
                
        # 移除多余的空格
        desc = " ".join(filter(None, desc.split()))
        return desc if desc else exp
            
    except Exception as e:
        print(f"解析cron表达式出错: {str(e)}")
        return exp

app = Flask(__name__, static_url_path='', static_folder='.')
# 使用当前目录作为基础目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_FOLDER = os.getenv('IMAGE_FOLDER', os.path.join(BASE_DIR, 'images'))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

# 初始化随机种子
random.seed(int(datetime.now().timestamp()))

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
            "cron_readable": translate_cron(cron_exp),
            "next_run": next_run,
            "current_image": current_image,
            "last_update": update_time_str
        })
    except Exception as e:
        print(f"获取调度信息失败: {str(e)}")
        return jsonify({
            "cron": cron_exp,
            "cron_readable": translate_cron(cron_exp),
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

class ImageFolderHandler(FileSystemEventHandler):
    def __init__(self, refresh_callback):
        self.refresh_callback = refresh_callback
        self.last_refresh_time = 0
        self.refresh_cooldown = 5  # 冷却时间（秒）

    def on_created(self, event):
        self._handle_event(event)

    def on_modified(self, event):
        self._handle_event(event)

    def on_moved(self, event):
        self._handle_event(event)

    def _handle_event(self, event):
        if event.is_directory:
            return
            
        # 检查文件扩展名
        if not event.src_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
            return
            
        # 检查冷却时间
        current_time = datetime.now().timestamp()
        if current_time - self.last_refresh_time < self.refresh_cooldown:
            return
            
        print(f"检测到图片变化: {event.src_path}")
        self.last_refresh_time = current_time
        self.refresh_callback()

if __name__ == '__main__':
    print("启动应用程序...")
    
    # 设置文件监控
    event_handler = ImageFolderHandler(scheduled_refresh)
    observer = Observer()
    observer.schedule(event_handler, IMAGE_FOLDER, recursive=False)
    observer.start()
    print(f"已启动文件监控: {IMAGE_FOLDER}")
    
    scheduled_refresh()  # 启动时立即加载
    
    # 设置环境变量禁用警告
    os.environ['WERKZEUG_RUN_MAIN'] = 'true'
    
    # 启动应用
    app.run(host='0.0.0.0', port=5000)