FROM python:3.9-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install -r requirements.txt

# 复制应用程序文件
COPY . .

# 创建必要的目录
RUN mkdir -p config images templates

# 暴露端口
EXPOSE 5000

# 启动应用
CMD ["python", "app.py"]