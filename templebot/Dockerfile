FROM python:3.7.7-slim
LABEL version="2.0.0a"
ENV PYTHONIOENCODING="UTF-8" LANG="en_GB.UTF-8"
WORKDIR /gchqbot
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
COPY . .
CMD ["python3", "run.py"]
