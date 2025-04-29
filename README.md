<img src="assets/image/logo.png" alt="随机图片&每日一图" width="200">

### 2025年4月28日，修改了docker的路径映射，请注意。

# 随机图片&每日一图

## Demo地址：

https://today-img.20160825.xyz

https://today-img.20160825.xyz/img/today.jpg


一个基于 Flask 的网页服务，提供随机图片和每日一图功能，支持本地文件夹（如 NAS）中的图片自动刷新显示。

## docker地址
`https://hub.docker.com/repository/docker/baozaolaowu/random-img-server/general`

## 功能特点

- 🖼️ 两种访问方式：
  - 网页界面（`http://localhost:5000`）：自动刷新，带设置按钮，浏览器全屏即可当作电子相册。
  - 直接图片链接（`http://localhost:5000/img/today.jpg`）：被动刷新，固定地址，强制无缓存，每次访问都会显示最新图片。

- 🔄 灵活的刷新选项：
  - 使用 cron 表达式自定义间隔
  - 手动刷新按钮
  - 标签页激活时自动刷新

- 📱 智能显示模式：
  - 智能模式（自动适应图片方向）
  - 宽度撑满模式
  - 高度撑满模式
  - 拉伸撑满模式

- 🚀 性能优化：
  - 图片缓存
  - 带宽感知更新
  - 非活动标签页资源节省

- 🎞️ 瀑布流模式：
  - 浏览多张图片的最佳方式
  - 多列自适应布局，可自定义列数（1-10列）
  - 文件夹导航与层级浏览
  - 图片排序功能（按文件名、创建时间、修改时间、随机顺序）
  - 图片全屏查看与缩放
  - 键盘导航（方向键切换图片，滚轮缩放，Ctrl+滚轮切换图片）
  - 自定义布局设置（列间距、图片间距、圆角大小）

## 应用场景

- 电子相框：自动轮播显示您的照片集
- 动态壁纸：配合支持 URL 图片的壁纸程序使用
- 主页背景：作为个人主页或仪表盘的背景
- 子面板背景：集成到 Homepage 或 Sub-panel 等工具，实现动态背景

## 快速开始

1. 创建配置目录：
```bash
# 创建配置和图片目录
mkdir -p /path/to/config /path/to/photos /path/to/thumbnails
```

2. 拉取 Docker 镜像：
```bash
docker pull baozaolaowu/random-img-server:latest
```

3. 运行容器：
```bash
docker run -d \
  -p 5000:5000 \
  -v "/path/to/config:/app/config" \
  -v "/path/to/photos:/app/photos" \
  -v "/path/to/thumbnails:/app/thumbnails" \
  --name random-img-server \
  baozaolaowu/random-img-server:latest
```

4. 访问服务：
- 网页界面：`http://localhost:5000`
- 直接图片链接：`http://localhost:5000/img/today.jpg`
- 瀑布流模式：`http://localhost:5000/waterfall`（或在主页面左下角点击"切换瀑布流模式"按钮）

## 配置说明

### 目录结构
```
/path/to/config/         # 配置文件目录
  └── config.json       # 定时任务配置文件
/path/to/images/         # 图片文件目录
  └── *.jpg,*.png,...  # 图片文件
```

### 图片要求
- 支持的格式：PNG、JPG、JPEG、GIF、BMP
- 最大文件大小：50MB

### Cron 表达式示例
- `*/5 * * * *` → 每5分钟
- `*/30 * * * *` → 每30分钟
- `0 * * * *` → 每小时整点
- `0 */2 * * *` → 每2小时
- `0 9 * * 1-5` → 工作日上午9点

## 使用方法

### 1. 网页访问
访问 `http://localhost:5000` 可以使用完整的网页界面，包含设置和手动刷新功能。

### 2. 直接图片链接

#### 基础用法（推荐）
```
http://localhost:5000/img/today.jpg
```
这个地址每次访问都会返回一张新的随机图片，适合在大多数场景下使用。

#### 在不同场景中使用

1. 在壁纸软件中：
```
# 直接填写这个地址即可
http://localhost:5000/img/today.jpg
```

2. 在 NAS 面板中：
```
http://localhost:5000/img/today.jpg
```

3. 在网页中使用：
```html
<!-- 基础用法 -->
<img src="http://localhost:5000/img/today.jpg">

<!-- 如果遇到缓存问题，可以使用JavaScript动态更新 -->
<script>
    const img = document.querySelector('img');
    function updateImage() {
        img.src = `http://localhost:5000/img/today.jpg?t=${Date.now()}`;
    }
    // 每分钟更新一次
    setInterval(updateImage, 60000);
</script>
```

#### 高级用法
如果遇到浏览器缓存问题，可以在链接后添加时间戳参数：
```
http://localhost:5000/img/today.jpg?t=123
```
注意：大多数情况下不需要添加时间戳，基础链接就能满足需求。

## 赞赏支持 Donate

如果您觉得这个项目对您有帮助，欢迎赞赏支持 👏

<div align="center">
  <img src="assets/image/donate/wx.jpg" alt="微信收款码" width="200" style="margin-right: 20px">
  <img src="assets/image/donate/zfb.jpg" alt="支付宝收款码" width="200">
</div>


---

# Random Image & Daily Picture

A Flask-based web service that provides random images and daily pictures from your local folder (e.g., NAS) with automatic refresh functionality.

## Demo：

https://today-img.20160825.xyz

https://today-img.20160825.xyz/img/today.jpg


## Features

- 🖼️ Two ways to access images:
  - Web interface (`http://localhost:5000`): Full control panel with display settings
  - Direct image URL (`http://localhost:5000/img/today.jpg`): Fixed URL that updates automatically

- 🔄 Flexible refresh options:
  - Customizable intervals using cron expressions
  - Manual refresh button
  - Auto-refresh when tab becomes active

- 📱 Smart display modes:
  - Smart mode (automatically adapts to image orientation)
  - Width fill mode
  - Height fill mode
  - Stretch fill mode

- 🚀 Performance optimized:
  - Image caching
  - Bandwidth-aware updates
  - Resource-saving when tab is inactive

- 🎞️ 瀑布流模式：
  - 浏览多张图片的最佳方式
  - 多列自适应布局，可自定义列数（1-10列）
  - 文件夹导航与层级浏览
  - 图片排序功能（按文件名、创建时间、修改时间、随机顺序）
  - 图片全屏查看与缩放
  - 键盘导航（方向键切换图片，滚轮缩放，Ctrl+滚轮切换图片）
  - 自定义布局设置（列间距、图片间距、圆角大小）

## Use Cases

- Digital Photo Frame: Display your photo collection with automatic rotation
- Dynamic Wallpaper: Use with wallpaper apps that support URL-based images
- Homepage Background: Perfect for homepage or dashboard background
- Sub-panel Background: Integrate with tools like Homepage or Sub-panel for dynamic backgrounds

## Quick Start

1. Create configuration directory:
```bash
# Create config and images directories
mkdir -p /path/to/config /path/to/photos /path/to/thumbnails
```

2. Pull the Docker image:
```bash
docker pull baozaolaowu/random-img-server:latest
```

3. Run the container:
```bash
docker run -d \
  -p 5000:5000 \
  -v "/path/to/config:/app/config" \
  -v "/path/to/photos:/app/photos" \
  -v "/path/to/thumbnails:/app/thumbnails" \
  --name random-img-server \
  baozaolaowu/random-img-server:latest
```

4. Access the service:
- Web interface: `http://localhost:5000`
- Direct image URL: `http://localhost:5000/img/today.jpg`
- 瀑布流模式：`http://localhost:5000/waterfall`（或在主页面左下角点击"切换瀑布流模式"按钮）

## Configuration

### Directory Structure
```
/path/to/config/         # Configuration directory
  └── config.json       # Cron job configuration file
/path/to/images/         # Images directory
  └── *.jpg,*.png,...  # Image files
```

### Image Requirements
- Supported formats: PNG, JPG, JPEG, GIF, BMP
- Maximum file size: 50MB

### Cron Expression Examples
- `*/5 * * * *` → Every 5 minutes
- `*/30 * * * *` → Every 30 minutes
- `0 * * * *` → Every hour
- `0 */2 * * *` → Every 2 hours
- `0 9 * * 1-5` → Weekdays at 9:00 AM

## Usage

### 1. Web Interface
Visit `http://localhost:5000` to access the full web interface with settings and manual refresh options.

### 2. Direct Image URL

#### Basic Usage (Recommended)
```
http://localhost:5000/img/today.jpg
```
This URL returns a new random image on each request, suitable for most use cases.

#### Use Cases

1. In Wallpaper Software:
```
# Simply use this URL
http://localhost:5000/img/today.jpg
```

2. In NAS Panel:
```
http://localhost:5000/img/today.jpg
```

3. In Web Pages:
```html
<!-- Basic usage -->
<img src="http://localhost:5000/img/today.jpg">

<!-- If caching issues occur, use JavaScript to update -->
<script>
    const img = document.querySelector('img');
    function updateImage() {
        img.src = `http://localhost:5000/img/today.jpg?t=${Date.now()}`;
    }
    // Update every minute
    setInterval(updateImage, 60000);
</script>
```

#### Advanced Usage
If you encounter browser caching issues, you can add a timestamp parameter:
```
http://localhost:5000/img/today.jpg?t=123
```
Note: In most cases, the basic URL is sufficient and no timestamp is needed.
