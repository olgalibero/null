import pandas as pd
import numpy as np
from binance.client import Client
from datetime import datetime
import time
import os
from dotenv import load_dotenv

# .env 파일에서 환경 변수 로드
load_dotenv()

# 환경 변수에서 API 키 가져오기
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')

client = Client(API_KEY, API_SECRET)

def get_futures_data(symbol, interval, limit=100):
    # 바이낸스 선물 데이터 가져오기
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume',
                                       'Close_time', 'Quote_asset_volume', 'Number_of_trades',
                                       'Taker_buy_base_volume', 'Taker_buy_quote_volume', 'Ignore'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
    return df

def calculate_position_size(symbol, position_pct, leverage):
    # 계좌 정보 가져오기
    account_info = client.futures_account()
    balance = float(account_info['totalWalletBalance'])
    
    # 사용 가능한 자산 계산 (USDT 기준)
    available_balance = balance * position_pct
    
    # 현재 가격 가져오기
    ticker = client.futures_symbol_ticker(symbol=symbol)
    current_price = float(ticker['price'])
    
    # 포지션 크기 계산 (계약 수량)
    quantity = (available_balance * leverage) / current_price
    # 최소 주문 단위에 맞게 반올림 (BTCUSDT: 0.001, ETHUSDT: 0.01)
    if symbol == 'BTCUSDT':
        quantity = round(quantity, 3)
    elif symbol == 'ETHUSDT':
        quantity = round(quantity, 2)
    else:
        quantity = round(quantity, 3)
    
    return quantity

def place_futures_order(symbol, side, quantity):
    # 레버리지 설정 (여기서는 10배로 고정)
    client.futures_change_leverage(symbol=symbol, leverage=10)
    
    # 시장가 주문 실행
    order = client.futures_create_order(
        symbol=symbol,
        side=side,
        type='MARKET',
        quantity=quantity,
    )
    return order

def run_strategy(symbol, k=0.5, position_pct=0.4, leverage=10):
    # 데이터 다운로드 (최근 100개 캔들)
    data = get_futures_data(symbol, Client.KLINE_INTERVAL_15MINUTE, limit=100)
    
    # 필요한 계산 수행
    data['High_prev'] = data['High'].shift(1)
    data['Low_prev'] = data['Low'].shift(1)
    data['Range'] = data['High_prev'] - data['Low_prev']
    
    # 매수 신호 계산
    data['Buy_Signal'] = data['Open'] + (data['Range'] * k)
    # 매도 신호 계산
    data['Sell_Signal'] = data['Open'] - (data['Range'] * k)
    
    # 최신 데이터 가져오기
    latest = data.iloc[-1]
    
    # 현재 포지션 정보 가져오기
    positions = client.futures_position_information(symbol=symbol)
    position_amt = float(positions[0]['positionAmt'])
    
    # 포지션 크기 계산
    quantity = calculate_position_size(symbol, position_pct, leverage)
    
    # 매수 신호 확인 (롱 포지션 진입)
    if latest['High'] > latest['Buy_Signal']:
        if position_amt == 0:
            # 롱 포지션 진입
            order = place_futures_order(symbol, 'BUY', quantity)
            print(f"{datetime.now()} - {symbol} 매수 주문 실행: 수량={quantity}")
        elif position_amt < 0:
            # 숏 포지션 청산 후 롱 포지션 진입
            close_order = place_futures_order(symbol, 'BUY', abs(position_amt))
            order = place_futures_order(symbol, 'BUY', quantity)
            print(f"{datetime.now()} - {symbol} 숏 포지션 청산 및 매수 주문 실행: 수량={quantity}")
        else:
            print(f"{datetime.now()} - {symbol} 이미 롱 포지션 보유 중")
    
    # 매도 신호 확인 (숏 포지션 진입)
    elif latest['Low'] < latest['Sell_Signal']:
        if position_amt == 0:
            # 숏 포지션 진입
            order = place_futures_order(symbol, 'SELL', quantity)
            print(f"{datetime.now()} - {symbol} 매도 주문 실행: 수량={quantity}")
        elif position_amt > 0:
            # 롱 포지션 청산 후 숏 포지션 진입
            close_order = place_futures_order(symbol, 'SELL', position_amt)
            order = place_futures_order(symbol, 'SELL', quantity)
            print(f"{datetime.now()} - {symbol} 롱 포지션 청산 및 매도 주문 실행: 수량={quantity}")
        else:
            print(f"{datetime.now()} - {symbol} 이미 숏 포지션 보유 중")
    else:
        print(f"{datetime.now()} - {symbol} 매매 신호 없음")
    
# 전략 실행 (15초마다)
if __name__ == "__main__":
    try:
        while True:
            # 비트코인 전략 실행
            run_strategy('BTCUSDT', k=0.5, position_pct=0.4, leverage=10)
            
            # 이더리움 전략 실행
            run_strategy('ETHUSDT', k=0.5, position_pct=0.4, leverage=10)
            
            # 15초 대기
            time.sleep(15)
    except KeyboardInterrupt:
        print("프로그램이 중지되었습니다.")
