FROM zauberzeug/nicegui:latest
WORKDIR /usr/app/
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
WORKDIR /usr/
ENTRYPOINT ["uvicorn", "app.main:app", "--reload", "--log-level", "debug", "--host", "0.0.0.0", "--port", "8080" ]
