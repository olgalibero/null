import os
import threading
import time
import pandas as pd
from binance.client import Client
from binance.enums import ORDER_TYPE_MARKET, SIDE_BUY, SIDE_SELL
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv  # dotenv 임포트

# .env 파일에서 환경 변수 로드
load_dotenv()

# 환경 변수에서 API 키 가져오기
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')

client = Client(API_KEY, API_SECRET)

# 공통 설정
SYMBOL = 'BTCUSDT'

def get_historical_data(symbol, interval, limit=100):
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        data = pd.DataFrame(klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        data['close'] = data['close'].astype(float)
        data['open'] = data['open'].astype(float)
        data['high'] = data['high'].astype(float)
        data['low'] = data['low'].astype(float)
        return data
    except BinanceAPIException as e:
        print(f"Error fetching historical data: {e}")
        return pd.DataFrame()

def calculate_movement(data, num_bars=6):
    if len(data) < num_bars:
        return 0
    recent = data.tail(num_bars)
    start = recent.iloc[0]['close']
    end = recent.iloc[-1]['close']
    movement = (end - start) / start
    return movement

def get_position_size(asset, percent):
    return asset * percent

def place_order(side, quantity, symbol=SYMBOL, leverage=10):
    try:
        # 레버리지 설정
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        
        # 시장가 주문
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )
        print(f"Placed {side} order for {quantity} {symbol}")
        return order
    except BinanceAPIException as e:
        print(f"Error placing order: {e}")
        return None

def get_account_balance():
    try:
        balance_info = client.futures_account_balance()
        usdt_balance = next((item for item in balance_info if item['asset'] == 'USDT'), None)
        if usdt_balance:
            return float(usdt_balance['balance'])
        else:
            return 0
    except BinanceAPIException as e:
        print(f"Error fetching account balance: {e}")
        return 0

def INTERVAL_TO_SECONDS(interval):
    mapping = {
        '1m': 60,
        '3m': 180,
        '5m': 300,
        '15m': 900,
        '30m': 1800,
        '1h': 3600,
        '2h': 7200,
        '4h': 14400,
        '6h': 21600,
        '8h': 28800,
        '12h': 43200,
        '1d': 86400,
        '3d': 259200,
        '1w': 604800,
        '1M': 2592000
    }
    return mapping.get(interval, 60)

class TradingStrategy(threading.Thread):
    def __init__(self, name, interval, leverage, position_size_percent, movement_threshold, max_hold_bars):
        threading.Thread.__init__(self)
        self.name = name
        self.interval = interval
        self.leverage = leverage
        self.position_size_percent = position_size_percent
        self.movement_threshold = movement_threshold
        self.max_hold_bars = max_hold_bars
        self.running = True

    def run(self):
        print(f"{self.name} started.")
        while self.running:
            try:
                data = get_historical_data(SYMBOL, self.interval, limit=self.max_hold_bars)
                if data.empty:
                    time.sleep(5)
                    continue

                movement = calculate_movement(data, num_bars=self.max_hold_bars)
                
                if abs(movement) >= self.movement_threshold:
                    retrace_level = data.iloc[-1]['close'] - (movement / 2) * data.iloc[-1]['close']
                    
                    current_price = float(client.get_symbol_ticker(symbol=SYMBOL)['price'])
                    
                    if (movement > 0 and current_price <= retrace_level) or (movement < 0 and current_price >= retrace_level):
                        account_balance = get_account_balance()
                        position_size = get_position_size(account_balance, self.position_size_percent) / current_price * self.leverage
                        
                        side = SIDE_BUY if movement < 0 else SIDE_SELL
                        order = place_order(side, position_size, leverage=self.leverage)
                        
                        if order:
                            entry_price = current_price
                            highest = entry_price
                            lowest = entry_price
                            bars_held = 0
                            
                            while bars_held < self.max_hold_bars:
                                current_price = float(client.get_symbol_ticker(symbol=SYMBOL)['price'])
                                highest = max(highest, current_price)
                                lowest = min(lowest, current_price)
                                
                                # 실시간 청산 조건
                                if side == SIDE_BUY and current_price >= highest:
                                    client.futures_create_order(
                                        symbol=SYMBOL,
                                        side=SIDE_SELL,
                                        type=ORDER_TYPE_MARKET,
                                        quantity=position_size
                                    )
                                    print(f"{self.name}: Position closed at market price {current_price}")
                                    break
                                elif side == SIDE_SELL and current_price <= lowest:
                                    client.futures_create_order(
                                        symbol=SYMBOL,
                                        side=SIDE_BUY,
                                        type=ORDER_TYPE_MARKET,
                                        quantity=position_size
                                    )
                                    print(f"{self.name}: Position closed at market price {current_price}")
                                    break
                                
                                bars_held += 1
                                time.sleep(INTERVAL_TO_SECONDS(self.interval) / self.max_hold_bars)
                            
                            # 최대 보유 시간 초과 시 청산
                            if bars_held >= self.max_hold_bars:
                                close_side = SIDE_SELL if side == SIDE_BUY else SIDE_BUY
                                client.futures_create_order(
                                    symbol=SYMBOL,
                                    side=close_side,
                                    type=ORDER_TYPE_MARKET,
                                    quantity=position_size
                                )
                                print(f"{self.name}: Position forcefully closed after max hold bars.")
                
                time.sleep(INTERVAL_TO_SECONDS(self.interval))
            
            except Exception as e:
                print(f"{self.name} encountered an error: {e}")
                time.sleep(5)
    
    def stop(self):
        self.running = False
        print(f"{self.name} stopped.")

def main():
    # 전략1 설정
    strategy1 = TradingStrategy(
        name="Strategy1",
        interval='4h',
        leverage=10,
        position_size_percent=0.5,  # 50%
        movement_threshold=0.03,    # 3%
        max_hold_bars=6
    )

    # 전략2 설정
    strategy2 = TradingStrategy(
        name="Strategy2",
        interval='1m',
        leverage=20,
        position_size_percent=0.25,  # 25%
        movement_threshold=0.015,    # 1.5%
        max_hold_bars=30
    )

    # 전략 시작
    strategy1.start()
    strategy2.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping strategies...")
        strategy1.stop()
        strategy2.stop()
        strategy1.join()
        strategy2.join()
        print("Strategies stopped.")

if __name__ == "__main__":
    main()
