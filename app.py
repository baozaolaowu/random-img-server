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
from PIL import Image
from io import BytesIO
import math
from concurrent.futures import ThreadPoolExecutor
import threading

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

# 在app.py中添加图片缓存和索引
IMAGE_CACHE = {}  # 缓存图片元数据，避免重复读取
SORT_CACHE = {}  # 缓存排序结果

# 在文件顶部添加新的全局变量，用于跟踪缩略图生成状态
THUMBNAIL_STATUS = {
    "is_generating": False,
    "total": 0,
    "processed": 0,
    "start_time": None,
    "current_file": ""
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
# 将图片目录改为photos子目录
PHOTOS_FOLDER = os.getenv('PHOTOS_FOLDER', os.path.join(BASE_DIR, 'photos'))
# 缩略图单独放在thumbnails子目录
THUMBNAIL_FOLDER = os.getenv('THUMBNAIL_FOLDER', os.path.join(BASE_DIR, 'thumbnails'))
CONFIG_FILE = os.path.join(CONFIG_FOLDER, 'config.json')

# 初始化随机种子
random.seed(int(datetime.now().timestamp()))

print(f"应用程序配置信息:")
print(f"BASE_DIR: {BASE_DIR}")
print(f"CONFIG_FOLDER: {CONFIG_FOLDER}")
print(f"PHOTOS_FOLDER: {PHOTOS_FOLDER}")
print(f"THUMBNAIL_FOLDER: {THUMBNAIL_FOLDER}")
print(f"CONFIG_FILE: {CONFIG_FILE}")

# 确保必要的目录存在
os.makedirs(CONFIG_FOLDER, exist_ok=True)
os.makedirs(PHOTOS_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

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

def generate_thumbnails_for_images(image_paths, max_concurrent=5):
    """为图片列表生成缩略图，限制并发数量"""
    global THUMBNAIL_STATUS
    
    print(f"开始生成缩略图，共 {len(image_paths)} 张图片")
    processed = 0
    lock = threading.Lock()
    
    # 更新状态
    THUMBNAIL_STATUS["is_generating"] = True
    THUMBNAIL_STATUS["total"] = len(image_paths)
    THUMBNAIL_STATUS["processed"] = 0
    THUMBNAIL_STATUS["start_time"] = datetime.now()
    
    def process_image(img_path):
        nonlocal processed
        try:
            # 更新当前处理的文件
            with lock:
                THUMBNAIL_STATUS["current_file"] = os.path.basename(img_path)
            
            # 获取相对路径
            rel_path = os.path.relpath(img_path, PHOTOS_FOLDER).replace('\\', '/')
            
            # 计算缩略图路径
            rel_dir = os.path.dirname(rel_path)
            thumb_dir = os.path.join(THUMBNAIL_FOLDER, rel_dir)
            os.makedirs(thumb_dir, exist_ok=True)
            
            # 使用多种尺寸
            for width in [200, 400, 800]:
                filename = os.path.basename(img_path)
                name, ext = os.path.splitext(filename)
                thumb_name = f"{name}_w{width}{ext}"
                thumb_path = os.path.join(thumb_dir, thumb_name)
                
                # 如果缩略图不存在，则创建
                if not os.path.exists(thumb_path):
                    with Image.open(img_path) as img:
                        # 保持原始比例
                        wpercent = (width / float(img.size[0]))
                        height = int((float(img.size[1]) * float(wpercent)))
                        
                        # 处理透明图片
                        if img.mode == 'RGBA':
                            background = Image.new('RGB', img.size, (255, 255, 255))
                            background.paste(img, mask=img.split()[3])
                            img = background
                        
                        # 调整大小
                        img_resized = img.resize((width, height), Image.LANCZOS)
                        
                        # 保存缩略图
                        img_resized.save(thumb_path, "JPEG", quality=85, optimize=True)
            
            with lock:
                processed += 1
                THUMBNAIL_STATUS["processed"] = processed
                if processed % 10 == 0 or processed == len(image_paths):
                    print(f"缩略图生成进度: {processed}/{len(image_paths)}")
                    
        except Exception as e:
            print(f"生成缩略图失败 {img_path}: {str(e)}")
    
    # 使用线程池限制并发
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        executor.map(process_image, image_paths)
    
    # 更新状态为完成
    THUMBNAIL_STATUS["is_generating"] = False
    THUMBNAIL_STATUS["current_file"] = ""
    
    print(f"缩略图生成完成，处理了 {processed} 张图片")

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
    
    # 先统计总文件数，排除缩略图目录
    for root, _, files in os.walk(directory):
        # 跳过缩略图目录
        if THUMBNAIL_FOLDER in root:
            print(f"跳过缩略图目录: {root}")
            continue
            
        SCAN_STATUS["total_files"] += len(files)
    
    # 然后处理文件，同样排除缩略图目录
    for root, _, files in os.walk(directory):
        # 跳过缩略图目录
        if THUMBNAIL_FOLDER in root:
            continue
            
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
    
    # 在后台启动缩略图生成任务
    if images:
        print("启动后台缩略图生成任务...")
        import threading
        thumbnail_thread = threading.Thread(
            target=generate_thumbnails_for_images,
            args=(images,),
            daemon=True
        )
        thumbnail_thread.start()
    
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
            
            # 读取文件夹设置
            folder_path = ""
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                folder_path = config.get('folderPath', '')
            except Exception as e:
                print(f"读取文件夹配置失败: {str(e)}")
            
            # 过滤图片列表
            filtered_images = CACHED_IMAGES
            if folder_path:
                folder_full_path = os.path.join(PHOTOS_FOLDER, folder_path)
                folder_full_path = os.path.normpath(folder_full_path)
                filtered_images = [img for img in CACHED_IMAGES 
                                 if os.path.normpath(img).startswith(folder_full_path)]
                
                if not filtered_images:
                    print(f"所选文件夹 '{folder_path}' 中没有图片，使用全部图片列表")
                    filtered_images = CACHED_IMAGES
                else:
                    print(f"已过滤图片列表，从 {len(CACHED_IMAGES)} 张缩小到 {len(filtered_images)} 张")
            else:
                print(f"使用全部图片列表 (共 {len(filtered_images)} 个)")
            
            # 选择新图片
            old_image = CURRENT_IMAGE.get('path')
            max_attempts = 5
            attempts = 0
            
            while attempts < max_attempts:
                selected_image = random.choice(filtered_images)
                if selected_image != old_image or len(filtered_images) == 1:
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
        args=[PHOTOS_FOLDER],
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
        # 获取文件夹参数（从请求URL参数获取）
        folder_path = request.args.get('folder', '')
        
        # 如果传入了文件夹参数，按指定文件夹返回图片
        # 这里不再修改config文件，避免配置干扰和竞争
        if folder_path:
            with lock:
                # 从全局图片列表筛选符合条件的图片
                folder_full_path = os.path.join(PHOTOS_FOLDER, folder_path)
                folder_full_path = os.path.normpath(folder_full_path)
                
                filtered_images = [img for img in CACHED_IMAGES 
                               if os.path.normpath(img).startswith(folder_full_path)]
                
                if not filtered_images:
                    # 如果没有找到图片，返回错误
                    return jsonify({"error": f"文件夹 '{folder_path}' 中没有有效图片"}), 404
                
                # 从筛选后的列表中随机选择一张
                selected_image = random.choice(filtered_images)
                
                # 验证文件
                if not os.path.isfile(selected_image):
                    return jsonify({"error": f"图片文件不存在: {selected_image}"}), 404
                
                # 获取文件信息
                file_info = get_file_info(selected_image)
                
                # 检查客户端缓存
                if_none_match = request.headers.get('If-None-Match')
                if if_none_match and if_none_match == file_info['etag']:
                    return '', 304
                
                # 设置响应头
                headers = {
                    'Cache-Control': 'public, max-age=60',  # 1分钟缓存
                    'ETag': file_info['etag'],
                    'Last-Modified': http_date(file_info['mtime']),
                    'Content-Type': mimetypes.guess_type(selected_image)[0],
                    'Content-Length': str(file_info['size'])
                }
                
                # 使用send_from_directory进行流式传输
                directory = os.path.dirname(selected_image)
                filename = os.path.basename(selected_image)
                return send_from_directory(
                    directory, 
                    filename, 
                    conditional=True,
                    download_name=filename,
                    as_attachment=False,
                    mimetype=headers['Content-Type']
                )
        
        # 以下是原有逻辑：使用当前全局设置的图片
        if not CURRENT_IMAGE.get('path'):
            # 如果没有当前图片，尝试刷新
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
    global LAST_REFRESH_TIME, CURRENT_IMAGE
    
    current_time = datetime.now()
    if LAST_REFRESH_TIME and (current_time - LAST_REFRESH_TIME).total_seconds() < REFRESH_COOLDOWN:
        return jsonify({
            "status": "error",
            "message": "刷新太频繁，请稍后再试"
        }), 429
    
    # 获取文件夹参数，支持URL参数
    folder_path = request.args.get('folder', '')
    
    # 如果传入了文件夹参数，从指定文件夹中随机选择一张图片
    if folder_path:
        with lock:
            try:
                # 从全局图片列表筛选符合条件的图片
                folder_full_path = os.path.join(PHOTOS_FOLDER, folder_path)
                folder_full_path = os.path.normpath(folder_full_path)
                
                filtered_images = [img for img in CACHED_IMAGES 
                               if os.path.normpath(img).startswith(folder_full_path)]
                
                if not filtered_images:
                    print(f"文件夹 '{folder_path}' 中没有有效图片")
                    return jsonify({
                        "status": "error",
                        "message": f"文件夹 '{folder_path}' 中没有有效图片"
                    }), 404
                
                # 从筛选后的列表中随机选择一张
                selected_image = random.choice(filtered_images)
                
                # 更新当前图片
                CURRENT_IMAGE['path'] = selected_image
                CURRENT_IMAGE['update_time'] = current_time
                
                LAST_REFRESH_TIME = current_time
                print(f"已从文件夹 '{folder_path}' 刷新图片: {selected_image}")
            except Exception as e:
                print(f"处理文件夹参数失败: {str(e)}")
                return jsonify({
                    "status": "error",
                    "message": f"处理文件夹参数失败: {str(e)}"
                }), 500
    else:
        # 如果没有文件夹参数，正常刷新
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
    """提供一个固定的图片访问地址，每次访问都会刷新图片"""
    try:
        # 每次访问都刷新图片
        scheduled_refresh()
        
        # 如果没有可用图片，返回404
        if not CURRENT_IMAGE.get('path'):
            return jsonify({"error": "没有可用的图片"}), 404
            
        # 验证文件是否存在且可访问
        if not os.path.isfile(CURRENT_IMAGE['path']):
            return jsonify({"error": f"图片文件不存在: {CURRENT_IMAGE['path']}"}), 404

        # 获取文件信息
        file_info = get_file_info(CURRENT_IMAGE['path'])
        
        # 获取更新时间作为版本号
        version = str(int(datetime.now().timestamp() * 1000))  # 使用毫秒级时间戳
        
        # 获取实际的文件MIME类型
        actual_mime_type = mimetypes.guess_type(CURRENT_IMAGE['path'])[0]
        
        # 设置响应头，强制浏览器不缓存
        response = send_file(
            CURRENT_IMAGE['path'],
            mimetype=actual_mime_type,
            conditional=True
        )
        
        # 更强力的缓存控制头
        response.headers.update({
            'Cache-Control': 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '-1',
            'Etag': f'W/"{version}"',  # 使用弱 ETag
            'Last-Modified': http_date(datetime.now().timestamp()),  # 使用当前时间
            'X-Version': version,
            'X-Original-Format': os.path.splitext(CURRENT_IMAGE['path'])[1][1:]
        })
        
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
        CACHED_IMAGES = get_all_images(PHOTOS_FOLDER)
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

# 新增路由: 瀑布流页面
@app.route('/waterfall')
def waterfall():
    return render_template('waterfall.html')

# 新增路由: 返回图片列表(支持分页)
@app.route('/list-images')
def list_images():
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        folder_path = request.args.get('path', '')
        sort_by = request.args.get('sort_by', 'name')
        sort_order = request.args.get('sort_order', 'asc')
        
        # 如果传入了exif排序，自动使用创建时间替代
        if sort_by == 'exif':
            sort_by = 'created'
        
        # 验证参数
        if page < 1: page = 1
        if limit < 1 or limit > 100: limit = 20
        
        # 生成缓存键
        cache_key = f"{folder_path}:{sort_by}:{sort_order}"
        
        # 构建目标文件夹的完整路径
        target_folder = os.path.join(PHOTOS_FOLDER, folder_path)
        
        # 安全检查，确保路径在photos目录内
        if not os.path.normpath(target_folder).startswith(os.path.normpath(PHOTOS_FOLDER)):
            return jsonify({"error": "无效的路径"}), 400
            
        # 检查是否有缓存的排序结果
        if cache_key in SORT_CACHE:
            all_images = SORT_CACHE[cache_key]
            print(f"使用缓存的排序结果: {len(all_images)}张图片")
        else:
            # 递归获取指定文件夹下的所有图片路径
            all_images = []
            
            for root, _, files in os.walk(target_folder):
                if THUMBNAIL_FOLDER in root:
                    continue
                    
                for f in files:
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                        full_path = os.path.join(root, f)
                        rel_path = os.path.relpath(full_path, PHOTOS_FOLDER).replace('\\', '/')
                        
                        # 检查是否已缓存该图片的元数据
                        if rel_path in IMAGE_CACHE:
                            image_info = IMAGE_CACHE[rel_path]
                        else:
                            # 获取基本文件信息
                            stat = os.stat(full_path)
                            image_info = {
                                "path": rel_path,
                                "name": f,
                                "created_time": stat.st_ctime,
                                "modified_time": stat.st_mtime,
                                "width": None,
                                "height": None
                            }
                            
                            # 获取图片尺寸但不再读取EXIF数据
                            try:
                                with Image.open(full_path) as img:
                                    image_info["width"], image_info["height"] = img.size
                            except Exception as e:
                                print(f"获取图片尺寸失败 {rel_path}: {str(e)}")
                            
                            # 缓存图片元数据
                            IMAGE_CACHE[rel_path] = image_info
                        
                        all_images.append(image_info)
            
            # 对图片列表排序
            if sort_by == 'name':
                all_images.sort(key=lambda x: x["name"].lower(), reverse=(sort_order == 'desc'))
            elif sort_by == 'created':
                all_images.sort(key=lambda x: x["created_time"], reverse=(sort_order == 'desc'))
            elif sort_by == 'modified':
                all_images.sort(key=lambda x: x["modified_time"], reverse=(sort_order == 'desc'))
            elif sort_by == 'random':
                # 随机排序时使用固定的随机种子，确保分页之间顺序一致
                seed = hash(folder_path) % 10000
                random.seed(seed)
                random.shuffle(all_images)
            
            # 缓存排序结果
            SORT_CACHE[cache_key] = all_images
            print(f"已缓存排序结果: {len(all_images)}张图片, 排序方式: {sort_by} {sort_order}")
        
        # 计算分页
        total = len(all_images)
        total_pages = math.ceil(total / limit)
        
        start_idx = (page - 1) * limit
        end_idx = min(start_idx + limit, total)
        
        # 获取当前页的图片
        current_page_images = all_images[start_idx:end_idx]
        
        return jsonify({
            "images": current_page_images,
            "page": page,
            "limit": limit,
            "total": total,
            "hasMore": page < total_pages,
            "sortBy": sort_by,
            "sortOrder": sort_order
        })
    except Exception as e:
        print(f"获取图片列表失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# 新增路由: 直接访问图片文件
@app.route('/img-static/<path:img_path>')
def get_static_image(img_path):
    try:
        # 防止路径遍历攻击
        normalized_path = os.path.normpath(img_path)
        if normalized_path.startswith('..'):
            return jsonify({"error": "无效的路径"}), 400
            
        image_path = os.path.join(PHOTOS_FOLDER, normalized_path)
        
        if not os.path.exists(image_path) or not os.path.isfile(image_path):
            return jsonify({"error": "图片不存在"}), 404
            
        return send_file(image_path)
    except Exception as e:
        print(f"获取图片出错: {str(e)}")
        return jsonify({"error": str(e)}), 500

# 生成缩略图并返回
@app.route('/img-thumbnail/<path:img_path>')
def get_thumbnail(img_path):
    try:
        # 防止路径遍历攻击
        normalized_path = os.path.normpath(img_path)
        if normalized_path.startswith('..'):
            return jsonify({"error": "无效的路径"}), 400
            
        original_path = os.path.join(PHOTOS_FOLDER, normalized_path)
        
        if not os.path.exists(original_path) or not os.path.isfile(original_path):
            return jsonify({"error": "图片不存在"}), 404
            
        # 计算缩略图路径 (保持目录结构)
        rel_dir = os.path.dirname(normalized_path)
        thumb_dir = os.path.join(THUMBNAIL_FOLDER, rel_dir)
        os.makedirs(thumb_dir, exist_ok=True)
        
        # 生成缩略图文件名 (使用原文件名+尺寸)
        width = int(request.args.get('w', 400))  # 默认宽度
        filename = os.path.basename(normalized_path)
        name, ext = os.path.splitext(filename)
        thumb_name = f"{name}_w{width}{ext}"
        thumb_path = os.path.join(thumb_dir, thumb_name)
        
        # 检查缩略图是否已存在
        if not os.path.exists(thumb_path):
            # 生成缩略图
            try:
                with Image.open(original_path) as img:
                    # 计算新高度，保持原始比例
                    wpercent = (width / float(img.size[0]))
                    height = int((float(img.size[1]) * float(wpercent)))
                    
                    # 如果图片是RGBA模式（带透明度），转换为RGB
                    if img.mode == 'RGBA':
                        # 创建白色背景
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        # 合并图片
                        background.paste(img, mask=img.split()[3])
                        img = background
                    
                    # 调整大小，使用高质量重采样
                    img_resized = img.resize((width, height), Image.LANCZOS)
                    
                    # 保存为JPEG格式，质量80%
                    img_resized.save(thumb_path, "JPEG", quality=80, optimize=True)
                    
            except Exception as e:
                print(f"缩略图生成失败: {str(e)}")
                # 如果缩略图生成失败，返回原图
                return send_file(original_path)
                
        # 返回缩略图
        return send_file(thumb_path)
            
    except Exception as e:
        print(f"获取缩略图出错: {str(e)}")
        return jsonify({"error": str(e)}), 500

# 获取瀑布流布局设置
@app.route('/get-waterfall-settings', methods=['GET'])
def get_waterfall_settings():
    try:
        # 读取配置文件
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 如果没有瀑布流设置，使用默认值
        waterfall_settings = config.get('waterfallSettings', {
            'columnCount': 3,
            'columnGap': 15,
            'imageGap': 15,
            'borderRadius': 8
        })
        
        return jsonify(waterfall_settings)
    except Exception as e:
        print(f"获取瀑布流设置失败: {str(e)}")
        return jsonify({
            'columnCount': 3,
            'columnGap': 15,
            'imageGap': 15,
            'borderRadius': 8
        })

# 保存瀑布流布局设置
@app.route('/save-waterfall-settings', methods=['POST'])
def save_waterfall_settings():
    try:
        settings = request.json
        
        # 验证设置
        required_fields = ['columnCount', 'columnGap', 'imageGap', 'borderRadius']
        for field in required_fields:
            if field not in settings:
                return jsonify({"error": f"缺少必要字段: {field}"}), 400
        
        # 读取现有配置
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 更新瀑布流设置
        config['waterfallSettings'] = settings
        
        # 保存到配置文件
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        return jsonify({"status": "success"})
    except Exception as e:
        error_msg = str(e)
        print(f"保存瀑布流设置失败: {error_msg}")
        return jsonify({"error": error_msg}), 500

# 获取文件夹结构
@app.route('/get-folders')
def get_folders():
    try:
        # 获取当前路径参数（相对路径）
        current_path = request.args.get('path', '')
        
        # 构建绝对路径
        target_path = os.path.join(PHOTOS_FOLDER, current_path)
        
        # 安全检查 - 确保路径在photos目录内
        if not os.path.normpath(target_path).startswith(os.path.normpath(PHOTOS_FOLDER)):
            return jsonify({"error": "无效的路径"}), 400
            
        # 如果路径不存在
        if not os.path.exists(target_path) or not os.path.isdir(target_path):
            return jsonify({"error": "目录不存在"}), 404
            
        # 获取当前目录下的所有子目录
        folders = []
        # 获取当前目录下的所有图片文件
        images = []
        
        for item in os.listdir(target_path):
            item_path = os.path.join(target_path, item)
            rel_path = os.path.join(current_path, item).replace('\\', '/')
            
            # 如果是目录，添加到文件夹列表
            if os.path.isdir(item_path):
                # 统计文件夹内的图片数量
                image_count = 0
                for root, _, files in os.walk(item_path):
                    for file in files:
                        if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                            image_count += 1
                
                folders.append({
                    "name": item,
                    "path": rel_path,
                    "imageCount": image_count
                })
            # 如果是图片文件，添加到图片列表
            elif item.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                images.append(rel_path)
        
        # 构建导航路径
        breadcrumbs = []
        if current_path:
            parts = current_path.split('/')
            current = ""
            for i, part in enumerate(parts):
                if part:  # 跳过空字符串
                    current = os.path.join(current, part)
                    breadcrumbs.append({
                        "name": part,
                        "path": current.replace('\\', '/')
                    })
        
        return jsonify({
            "currentPath": current_path,
            "breadcrumbs": breadcrumbs,
            "folders": folders,
            "images": images
        })
        
    except Exception as e:
        print(f"获取文件夹结构失败: {str(e)}")
        return jsonify({"error": str(e)}), 500

# 添加清除缓存的API
@app.route('/clear-cache', methods=['POST'])
def clear_cache():
    global IMAGE_CACHE, SORT_CACHE
    IMAGE_CACHE = {}
    SORT_CACHE = {}
    return jsonify({"status": "success", "message": "缓存已清除"})

# 保存文件夹设置
@app.route('/save-folder-setting', methods=['POST'])
def save_folder_setting():
    try:
        folder_path = request.json.get('folder', '')
        
        # 读取现有配置
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 更新文件夹设置
        config['folderPath'] = folder_path
        
        # 保存到配置文件
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        return jsonify({"status": "success"})
    except Exception as e:
        error_msg = str(e)
        print(f"保存文件夹设置失败: {error_msg}")
        return jsonify({"error": error_msg}), 500

# 获取当前文件夹设置
@app.route('/get-folder-setting', methods=['GET'])
def get_folder_setting():
    try:
        # 读取配置文件
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 获取文件夹路径设置
        folder_path = config.get('folderPath', '')
        
        return jsonify({"folder": folder_path})
    except Exception as e:
        print(f"获取文件夹设置失败: {str(e)}")
        return jsonify({"folder": ""})

# 添加一个新的API端点，用于获取缩略图生成状态
@app.route('/thumbnail-status', methods=['GET'])
def get_thumbnail_status():
    """获取缩略图生成状态"""
    global THUMBNAIL_STATUS
    status = THUMBNAIL_STATUS.copy()
    if status["start_time"]:
        duration = (datetime.now() - status["start_time"]).total_seconds()
        status["duration"] = round(duration, 2)
    else:
        status["duration"] = 0
    return jsonify(status)

if __name__ == '__main__':
    print("启动应用程序...")
    
    # 设置文件监控
    event_handler = ImageFolderHandler(scheduled_refresh)
    observer = Observer()
    observer.schedule(event_handler, PHOTOS_FOLDER, recursive=True)
    observer.start()
    print(f"已启动文件监控（包含子文件夹）: {PHOTOS_FOLDER}")
    
    # 启动时扫描目录
    print("执行初始目录扫描...")
    CACHED_IMAGES = get_all_images(PHOTOS_FOLDER)
    LAST_SCAN_TIME = datetime.now()
    
    # 设置环境变量禁用警告
    os.environ['WERKZEUG_RUN_MAIN'] = 'true'
    
    # 启动应用
    app.run(host='0.0.0.0', port=5000)