import yfinance as yf
import pandas as pd
import requests
import time
import schedule
from datetime import datetime
import pytz

# ============================================================
#  CONFIGURAÇÕES — EDITE APENAS ESTA SEÇÃO
# ============================================================

import os
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Lista de ações para monitorar
# Ações brasileiras (B3): sempre com .SA no final
# Ações americanas: sem sufixo
ACOES = [
    "PETR4.SA",
    "VALE3.SA",
    "ITUB4.SA",
    "WEGE3.SA",
    "BBDC4.SA",
    "MGLU3.SA",
    "AAPL",
    "NVDA",
    "MSFT",
    "TSLA",
    # EUA — sem sufixo
    "AAPL",  # Apple
    "GOOGL",  # Google
]

# Critérios de análise (você pode ajustar estes valores)
RSI_LIMITE           = 30   # Alerta se RSI estiver abaixo deste número
VOLUME_MULTIPLICADOR = 1.5  # Alerta se volume for X vezes a média de 20 dias
MIN_CRITERIOS        = 1    # Mínimo de critérios simultâneos para notificar

# ============================================================
#  CÓDIGO DO ROBÔ — NÃO PRECISA ALTERAR ABAIXO
# ============================================================

alertas_enviados = {}

def calcular_rsi(close, periodo=14):
    delta = close.diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)
    media_ganho = ganho.rolling(periodo).mean()
    media_perda = perda.rolling(periodo).mean()
    rs = media_ganho / media_perda
    return 100 - (100 / (1 + rs))

def calcular_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    sinal = macd.ewm(span=9, adjust=False).mean()
    return macd, sinal

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"Erro Telegram: {r.text}")
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")

def analisar_acao(ticker):
    try:
        dados = yf.download(ticker, period="3mo", interval="1d",
                            progress=False, auto_adjust=True)
        if dados.empty or len(dados) < 55:
            print(f"  {ticker}: dados insuficientes")
            return

        close  = dados["Close"].squeeze()
        volume = dados["Volume"].squeeze()

        criterios = []
        detalhes  = []

        # ── Critério 1: RSI abaixo do limite ──────────────────
        rsi       = calcular_rsi(close)
        rsi_atual = round(float(rsi.iloc[-1]), 1)
        if rsi_atual < RSI_LIMITE:
            criterios.append("RSI")
            detalhes.append(f"📉 RSI em {rsi_atual} (sobrevendida)")

        # ── Critério 2: Cruzamento da Média Móvel de 50 dias ──
        ma50          = close.rolling(50).mean()
        preco_hoje    = float(close.iloc[-1])
        preco_ontem   = float(close.iloc[-2])
        ma50_hoje     = float(ma50.iloc[-1])
        ma50_ontem    = float(ma50.iloc[-2])
        if preco_ontem <= ma50_ontem and preco_hoje > ma50_hoje:
            criterios.append("MA50")
            detalhes.append("📈 Cruzou a Média de 50 dias para cima")

        # ── Critério 3: MACD cruzando a linha de sinal ────────
        macd_line, sinal_line = calcular_macd(close)
        if (float(macd_line.iloc[-2]) < float(sinal_line.iloc[-2]) and
                float(macd_line.iloc[-1]) > float(sinal_line.iloc[-1])):
            criterios.append("MACD")
            detalhes.append("⚡ MACD cruzou linha de sinal (momentum +)")

        # ── Critério 4: Volume acima da média ─────────────────
        vol_media = float(volume.rolling(20).mean().iloc[-1])
        vol_hoje  = float(volume.iloc[-1])
        if vol_hoje > vol_media * VOLUME_MULTIPLICADOR:
            criterios.append("VOLUME")
            mult = round(vol_hoje / vol_media, 1)
            detalhes.append(f"🔊 Volume {mult}× acima da média")

        # ── Verificar se atingiu o mínimo de critérios ────────
        qtd = len(criterios)
        print(f"  {ticker}: {qtd} critério(s) atingido(s) {criterios}")

        if qtd >= MIN_CRITERIOS:
            chave = f"{ticker}_{'_'.join(sorted(criterios))}"
            hoje  = datetime.now().strftime("%Y-%m-%d")

            if alertas_enviados.get(chave) == hoje:
                print(f"  {ticker}: alerta já enviado hoje, pulando.")
                return

            alertas_enviados[chave] = hoje

            nome  = ticker.replace(".SA", "")
            moeda = "R$" if ".SA" in ticker else "US$"
            preco_fmt = f"{moeda} {preco_hoje:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            mensagem = (
                f"🚨 <b>OPORTUNIDADE DE COMPRA — {nome}</b>\n\n"
                f"💰 Preço atual: {preco_fmt}\n"
                f"✅ <b>{qtd} de 4 critérios atingidos:</b>\n"
                + "\n".join(f"   • {d}" for d in detalhes)
                + f"\n\n⚠️ <i>Análise técnica automática. Não é recomendação de investimento. Consulte um assessor antes de operar.</i>"
            )
            enviar_telegram(mensagem)
            print(f"  ✅ Alerta enviado para {ticker}!")

    except Exception as e:
        print(f"  Erro ao analisar {ticker}: {e}")

def verificar_todas():
    tz    = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(tz)
    hora  = agora.hour
    dia   = agora.weekday()  # 0 = segunda-feira, 6 = domingo

    print(f"\n[{agora.strftime('%d/%m %H:%M')}] Iniciando verificação...")

    if dia >= 5:
        print("  Fim de semana — mercado fechado. Aguardando...")
        return

    if hora < 10 or hora >= 18:
        print("  Fora do horário de mercado (10h–18h). Aguardando...")
        return

    print(f"  Analisando {len(ACOES)} ações:")
    for ticker in ACOES:
        analisar_acao(ticker)
        time.sleep(1.5)  # Pausa entre chamadas para não sobrecarregar a API

    print("  Varredura concluída.")

# Executa imediatamente ao iniciar e depois a cada 1 hora
verificar_todas()
schedule.every(1).hours.do(verificar_todas)

print("\nRobô ativo! Verificando a cada hora durante o pregão.")
print("Pressione Ctrl+C para encerrar.\n")

while True:
    schedule.run_pending()
    time.sleep(60)