# Backend — schlankes Abbild, nicht-privilegierter Nutzer.
FROM python:3.11-slim

WORKDIR /app

# Abhängigkeiten zuerst: Sie ändern sich selten, der Code bei jedem Bau.
# Umgekehrt wäre jede Codeänderung ein vollständiger Neubau der Schicht.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

COPY app ./app

# Olares erlaubt kein root im Container. Die UID 1000 passt zu den
# Rechten, die der init-Container auf /app/data und /app/cache setzt.
RUN useradd --uid 1000 --create-home aicrm && chown -R 1000:1000 /app
USER 1000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
