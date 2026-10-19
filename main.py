name: Sincronizador LicitaLAB RedSalud

on:
  schedule:
    - cron: '0 8 * * *'  # Ejecución diaria programada
  workflow_dispatch:      # Permite ejecución manual

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout del código
        uses: actions/checkout@v3

      - name: Configurar Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Instalar librerías necesarias
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Ejecutar Sincronizador
        env:
          GCP_JSON_BASE64: ${{ secrets.GCP_JSON_BASE64 }}
          LICITALAB_API_KEY: ${{ secrets.LICITALAB_API_KEY }}
        run: python main.py
