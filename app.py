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

# 在文件顶部添加缓存变量
CACHED_IMAGES = []
LAST_SCAN_TIME = None
CACHE_DURATION = 300  # 缓存有效期（秒）
LAST_REFRESH_TIME = None
REFRESH_COOLDOWN = 0.1  # 刷新冷却时间（秒）

# 在文件顶部添加新的全局变量
SCAN_STATUS = {
    "is_scanning": False,
    "total_files": 0,
    "processed_files": 0,
    "valid_images": 0,
    "skipped_files": 0,
    "current_file": "",
    "start_time": None
}

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
CONFIG_FOLDER = os.getenv('CONFIG_FOLDER', os.path.join(BASE_DIR, 'config'))
IMAGE_FOLDER = os.getenv('IMAGE_FOLDER', os.path.join(BASE_DIR, 'images'))
CONFIG_FILE = os.path.join(CONFIG_FOLDER, 'config.json')

# 初始化随机种子
random.seed(int(datetime.now().timestamp()))

print(f"应用程序配置信息:")
print(f"BASE_DIR: {BASE_DIR}")
print(f"CONFIG_FOLDER: {CONFIG_FOLDER}")
print(f"IMAGE_FOLDER: {IMAGE_FOLDER}")
print(f"CONFIG_FILE: {CONFIG_FILE}")

# 确保必要的目录存在
os.makedirs(CONFIG_FOLDER, exist_ok=True)
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

def get_all_images(directory):
    """递归获取目录下所有图片文件"""
    global SCAN_STATUS
    SCAN_STATUS["is_scanning"] = True
    SCAN_STATUS["start_time"] = datetime.now()
    SCAN_STATUS["total_files"] = 0
    SCAN_STATUS["processed_files"] = 0
    SCAN_STATUS["valid_images"] = 0
    SCAN_STATUS["skipped_files"] = 0
    
    start_time = SCAN_STATUS["start_time"]
    images = []
    print(f"\n[{start_time}] 开始扫描图片目录: {directory}")
    
    # 先统计总文件数
    for root, _, files in os.walk(directory):
        SCAN_STATUS["total_files"] += len(files)
    
    # 然后处理文件
    for root, _, files in os.walk(directory):
        for f in files:
            SCAN_STATUS["processed_files"] += 1
            SCAN_STATUS["current_file"] = f
            
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                file_path = os.path.join(root, f)
                try:
                    file_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
                    if file_size <= 50:  # 限制50MB
                        images.append(file_path)
                        SCAN_STATUS["valid_images"] += 1
                        print(f"添加文件: {f} ({file_size:.1f}MB)")
                    else:
                        SCAN_STATUS["skipped_files"] += 1
                        print(f"跳过大文件: {f} ({file_size:.1f}MB)")
                except Exception as e:
                    print(f"读取文件出错 {f}: {str(e)}")
                    SCAN_STATUS["skipped_files"] += 1
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    print(f"\n扫描完成统计:")
    print(f"- 总文件数: {SCAN_STATUS['total_files']}")
    print(f"- 有效图片: {SCAN_STATUS['valid_images']}")
    print(f"- 跳过文件: {SCAN_STATUS['skipped_files']}")
    print(f"- 扫描用时: {duration:.2f}秒")
    
    SCAN_STATUS["is_scanning"] = False
    return images

def scheduled_refresh():
    """定时刷新图片"""
    global CACHED_IMAGES, LAST_SCAN_TIME
    
    with lock:
        try:
            start_time = datetime.now()
            print(f"\n[{start_time}] 开始刷新图片...")

            # 如果没有缓存，返回错误
            if not CACHED_IMAGES:
                print("没有缓存的图片列表，请先扫描目录")
                return
                
            print(f"使用缓存中的图片列表 (共 {len(CACHED_IMAGES)} 个)")
            
            # 选择新图片
            old_image = CURRENT_IMAGE.get('path')
            max_attempts = 5
            attempts = 0
            
            while attempts < max_attempts:
                selected_image = random.choice(CACHED_IMAGES)
                if selected_image != old_image or len(CACHED_IMAGES) == 1:
                    break
                attempts += 1
                print(f"尝试选择不同的图片 (尝试 {attempts}/{max_attempts})")
            
            print(f"选中图片: {selected_image}")
            
            # 验证文件
            if not os.path.isfile(selected_image):
                print(f"文件不存在，从缓存中移除: {selected_image}")
                CACHED_IMAGES.remove(selected_image)
                return
                
            try:
                # 测试文件可读性
                with open(selected_image, 'rb') as f:
                    f.read(1)
                print("文件可以正常读取")
            except Exception as e:
                print(f"文件无法读取: {str(e)}")
                CACHED_IMAGES.remove(selected_image)
                return
                
            CURRENT_IMAGE['path'] = selected_image
            CURRENT_IMAGE['update_time'] = start_time
            CURRENT_IMAGE['info'] = get_file_info(selected_image)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            file_size = os.path.getsize(selected_image) / (1024 * 1024)
            print(f"\n刷新完成:")
            print(f"- 新图片: {os.path.basename(selected_image)}")
            print(f"- 文件大小: {file_size:.1f}MB")
            print(f"- 总用时: {duration:.2f}秒")
            
        except Exception as e:
            print(f"刷新图片时发生错误: {str(e)}")
            import traceback
            print(traceback.format_exc())

# 初始化调度器
scheduler = BackgroundScheduler(daemon=True, timezone='Asia/Shanghai')
scheduler.start()

# 添加定时扫描任务（每30分钟扫描一次）
try:
    scan_job = scheduler.add_job(
        get_all_images, 
        'interval', 
        minutes=30,
        id='scan_task',
        args=[IMAGE_FOLDER],
        next_run_time=None  # 不立即执行，因为启动时已经执行过了
    )
    print("已设置目录扫描任务: 每30分钟")
    if scan_job and scan_job.next_run_time:
        print(f"下次扫描时间: {scan_job.next_run_time}")
except Exception as e:
    print(f"设置扫描任务失败: {str(e)}")

# 解析当前的cron表达式（原有的刷新任务）
try:
    cron_dict = parse_cron(cron_exp)
    job = scheduler.add_job(scheduled_refresh, 'cron', id='refresh_task', **cron_dict)
    print(f"已设置定时刷新任务: {cron_exp}")
    if job and job.next_run_time:
        print(f"下次刷新时间: {job.next_run_time}")
except Exception as e:
    print(f"设置定时刷新任务失败，使用默认值: {str(e)}")
    job = scheduler.add_job(scheduled_refresh, 'cron', id='refresh_task', minute='*/1')
    if job and job.next_run_time:
        print(f"已设置默认定时刷新任务，下次执行时间: {job.next_run_time}")

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
    global LAST_REFRESH_TIME
    
    current_time = datetime.now()
    if LAST_REFRESH_TIME and (current_time - LAST_REFRESH_TIME).total_seconds() < REFRESH_COOLDOWN:
        return jsonify({
            "status": "error",
            "message": "刷新太频繁，请稍后再试"
        }), 429
        
    LAST_REFRESH_TIME = current_time
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

@app.route('/scan', methods=['POST'])
def scan_directory():
    """扫描目录的API端点"""
    global CACHED_IMAGES, LAST_SCAN_TIME
    
    try:
        start_time = datetime.now()
        print("\n开始手动扫描目录...")
        
        # 执行扫描
        CACHED_IMAGES = get_all_images(IMAGE_FOLDER)
        LAST_SCAN_TIME = datetime.now()
        
        duration = (LAST_SCAN_TIME - start_time).total_seconds()
        
        return jsonify({
            "status": "success",
            "total_files": len(CACHED_IMAGES),
            "valid_images": len(CACHED_IMAGES),
            "duration": round(duration, 2)
        })
        
    except Exception as e:
        print(f"扫描目录时发生错误: {str(e)}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

@app.route('/scan-status', methods=['GET'])
def get_scan_status():
    """获取扫描状态"""
    global SCAN_STATUS
    status = SCAN_STATUS.copy()
    if status["start_time"]:
        duration = (datetime.now() - status["start_time"]).total_seconds()
        status["duration"] = round(duration, 2)
    else:
        status["duration"] = 0
        
    # 添加任务类型标识
    status["is_manual_scan"] = request.args.get('manual', 'false') == 'true'
    return jsonify(status)

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
    observer.schedule(event_handler, IMAGE_FOLDER, recursive=True)
    observer.start()
    print(f"已启动文件监控（包含子文件夹）: {IMAGE_FOLDER}")
    
    # 启动时扫描目录
    print("执行初始目录扫描...")
    CACHED_IMAGES = get_all_images(IMAGE_FOLDER)
    LAST_SCAN_TIME = datetime.now()
    
    # 设置环境变量禁用警告
    os.environ['WERKZEUG_RUN_MAIN'] = 'true'
    
    # 启动应用
    app.run(host='0.0.0.0', port=5000)