# Backend — schlankes Abbild, nicht-privilegierter Nutzer.
FROM python:3.11-slim

WORKDIR /app

# Abhängigkeiten zuerst: Sie ändern sich selten, der Code bei jedem Bau.
# Umgekehrt wäre jede Codeänderung ein vollständiger Neubau der Schicht.
# Das Paket selbst lässt sich ohne app/ nicht bauen (setuptools sucht das
# Verzeichnis), also werden hier nur die Abhängigkeiten aus dem
# pyproject gelesen und installiert — das Paket kommt danach.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
 && python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/req.txt \
 && pip install --no-cache-dir -r /tmp/req.txt

COPY app ./app
RUN pip install --no-cache-dir --no-deps .

# Olares erlaubt kein root im Container. Die UID 1000 passt zu den
# Rechten, die der init-Container auf /app/data und /app/cache setzt.
RUN useradd --uid 1000 --create-home aicrm && chown -R 1000:1000 /app
USER 1000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
