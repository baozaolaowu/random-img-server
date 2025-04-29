FROM python:3.9-slim

WORKDIR /app

# 复制项目文件
COPY . .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 确保应用使用这些路径
ENV CONFIG_FOLDER=/app/config
ENV PHOTOS_FOLDER=/app/photos
ENV THUMBNAIL_FOLDER=/app/thumbnails

# 创建必要的目录
RUN mkdir -p /app/config /app/photos /app/thumbnails

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["python", "app.py"]