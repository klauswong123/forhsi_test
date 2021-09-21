from futu import *
from datetime import datetime
import time
from call_15min_data import quote_15mins
import pymongo
import logging, os

monthlog = str(datetime.now()).split()[0][:-3]
if not os.path.isfile(f'log/output_{monthlog}.log'):
    f=open(f'log/output_{monthlog}.log','w')
    f.close()
logging.basicConfig(level=logging.DEBUG,
                    filename=f'log/output_{monthlog}.log',
                    datefmt='%Y/%m/%d %H:%M:%S',
                    format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


class HSI_strategy:
    def __init__(self,):
        #define stock quantity, stock code, holiday date
        self.qty = 1
        self.StockCodeHeader = 'HK.MHI'
        self.holiday = ['0405', '0406', '0519', '0614', '0701', '0922', '1001', '1014', '1227']
        #connect to mongodb for trade data
        self.client = pymongo.MongoClient("mongodb://localhost:27017/")
        self.hsicurrent = self.client["hsicurrent"]
        self.trade_history = self.hsicurrent["trade_record_15mins"]
        #start futu api connection and trade
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        self.trd_ctx = OpenFutureTradeContext(host='127.0.0.1', port=11111)
        pwd_unlock = '636123'
        self.trd_ctx.unlock_trade(pwd_unlock)
        #start trade strategy
        self.endOfTrade = False
        errorCount = 0
        while True:
            if errorCount>5:
                break
            try:
                self.nextLoop = False
                self.trade_strategy()
            except Exception as e:
                print(e)
                print("Error Happen!! Please Check!!")
                logger.info("Error Happen!! Please Check!!")
                errorCount=errorCount+1
        self.quote_ctx.close()
        self.client.close()
        self.trd_ctx.close()

    def trade_strategy(self):
        #check last trade status
        quote_15mins()
        #check Stock Code
        self.accident=False
        self.StockCode = self.get_StockCode()
        print(f"Stock Code: {self.StockCode}")
        logger.info(f"Stock Code: {self.StockCode}")
        self.buy_status=''
        self.check_trade_status()
        self.trend, lasttrend = self.buy_status,''
        while not self.endOfTrade:
            #pause to between trade
            self.check_holiday_pause()
            self.check_weekend_pause()
            self.check_market_pause()
            if self.accident:
                self.check_accident()
                self.accident=False
            if self.nextLoop:
                self.nextLoop = False
                #update 15 Mins Data
                quote_15mins()
                #update Stock Code
                if not self.buy:
                    self.StockCode = self.get_StockCode()
                print(f"Stock Code: {self.StockCode}")
                self.refreshData()
                continue
            self.check_data_pause()
            self.get_current()
            if self.accident:
                continue
            if lasttrend=='':
                if self.dea < self.diff and not self.buy:
                    lasttrend = 'up'
                elif self.dea > self.diff and not self.buy:
                    lasttrend = 'down'
            if self.dea <= self.diff and not self.buy:
                self.trend = 'up'
            elif self.dea > self.diff and not self.buy:
                self.trend = 'down'
            if lasttrend != self.trend:
                lasttrend = 'pass'
                pass
            else:
                time.sleep(90)
                continue
            if not self.buy:
                if self.trend == 'up':
                    self.buy = True
                    self.buy_price = self.close
                    self.buy_status = 'up'
                    self.buy_time = str(datetime.now())
                    self.buyIn()
                    continue
                if self.trend == 'down':
                    self.buy = True
                    self.buy_price = self.close
                    self.buy_status = 'down'
                    self.buy_time = str(datetime.now())
                    self.sellShort()
                    continue
                continue
            if self.buy:
                if self.trend == 'down':
                    if str(self.diff >= self.dea) == 'True':
                        self.sell = True
                        self.sell_price = self.close
                        self.buyBack()
                        if self.buy_status == 'up':
                            self.benefit = (float(self.sell_price) - float(self.buy_price) - 2) * 10
                        else:
                            self.benefit = (float(self.buy_price) - float(self.sell_price) - 2) * 10
                elif self.trend == 'up':
                    if str(self.dea > self.diff) == 'True':
                        self.sell = True
                        self.sell_price = self.close
                        self.sellOut()
                        if self.buy_status == 'up':
                            self.benefit = (float(self.sell_price) - float(self.buy_price) - 2) * 10
                        else:
                            self.benefit = (float(self.buy_price) - float(self.sell_price) - 2) * 10
            if self.sell:
                self.sell = False
                self.sell_price = None
                self.buy = False
                self.buy_price = 0
                if not self.buy:
                    if self.dea <= self.diff:
                        self.trend = 'up'
                    elif self.dea > self.diff:
                        self.trend = 'down'
                    if self.trend == 'up':
                        self.buy = True
                        self.buy_status = 'up'
                        self.buyIn()
                        print(
                            f"Status:{self.buy_status} Buy: {self.buy} Buy Time:{self.buy_time}; dea:{self.dea} diff:{self.diff} \n")
                        logger.info(f"Status:{self.buy_status} Buy: {self.buy} Buy Time:{self.buy_time}; dea:{self.dea} diff:{self.diff}\n")
                        continue
                    if self.trend == 'down':
                        self.buy = True
                        self.buy_status = 'down'
                        self.sellShort()
                        print(
                            f"Status:{self.buy_status} Buy: {self.buy_price} Buy Time:{self.buy_time};\ndea:{self.dea} diff:{self.diff} \n")
                        logger.info(
                            f"Status:{self.buy_status} Buy: {self.buy} Buy Time:{self.buy_time}; dea:{self.dea} diff:{self.diff}\n")
                        continue
            time.sleep(90)


    def get_current(self):
        data = self.quote_ctx.get_market_snapshot([self.StockCode])
        self.ifupdate=False
        counterror = 0
        while not self.ifupdate:
            if counterror > 6:
                self.accident=True
                return 0
            try:
                self.close = float(str(data[1]['last_price']).split()[1])
                self.timekey = ' ' .join(str(data[1]['update_time']).split()[1:3])
                self.ema_20,self.ema_25 = self.calculate_ema(close=self.close,ema_20=self.ema_20,ema_25=self.ema_25)
                self.diff, self.dea = self.calculate_macd(ema_20=self.ema_20,ema_25=self.ema_25, lastdea=self.dea)
                self.ifupdate = True
                print(f"Time: {str(datetime.now()).split('.')[0]} Close: {self.close} Trend: {self.trend} Diff: {self.diff} Dea: {self.dea}")
                logger.info(f"Time: {str(datetime.now()).split('.')[0]} Close: {self.close} Trend: {self.trend} Diff: {self.diff} Dea: {self.dea}")
            except Exception as e:
                counterror=counterror+1
                print(e)
                logger.info(e)

    def calculate_macd(self, ema_20, ema_25, lastdea):
        diff = float(ema_20) - float(ema_25)
        dea = float(lastdea) * 0.8 + diff * 0.2
        return float(diff), float(dea)

    def calculate_ema(self,close,ema_20,ema_25):
        ema_20 = (19 * float(ema_20) + 2 * close) / 21
        ema_25 = (24 * float(ema_25) + 2 * close) / 26
        return float(ema_20), float(ema_25)

    #refresh time for pause
    def refresh_time(self):
        currentTime = datetime.now()
        self.today = str(currentTime).split()[0]
        self.weekday = currentTime.weekday()
        self.hour = str(currentTime).split()[1].split(":")[0]
        self.mins = str(currentTime).split()[1].split(":")[1]
        self.second = str(currentTime).split()[1].split(":")[2].split(".")[0]
        self.month = str(currentTime).split()[0].split("-")[1]
        self.day = str(currentTime).split()[0].split("-")[2]

    #check holiday pause:
    def check_holiday_pause(self):
        self.refresh_time()
        if (self.month + self.day) in self.holiday:
            if int(self.hour) >= 3:
                sleepTime = (24 * 3600) - (int(self.hour) * 3600 + int(self.mins) * 60 + int(self.second)) + 3 * 3600 + 150
                print(f"Holiday {self.month}/{self.day} Sleep till tmr 3:00")
                logger.info(f"Holiday {self.month}/{self.day} Sleep till tmr 3:00")
                time.sleep(sleepTime)
                self.nextLoop = True
                return 0

    #check weekend pause:
    def check_weekend_pause(self):
        self.refresh_time()
        if (int(self.weekday) == 5 and int(self.hour) >= 3) or int(self.weekday) == 6:
            if int(self.hour) == 0 and int(self.mins) == 0:
                print(f"Weekend：Sleep till tmr 03:00. Now is {self.weekday+1}")
                logger.info(f"Weekend：Sleep till tmr 03:00. Now is {self.weekday+1}")
                time.sleep(86400+3*3600+30)
                print(str(datetime.now()))
                self.nextLoop = True
                return 0
            else:
                sleepTime = (23 - int(self.hour) + 3 ) * 3600 + (59 - int(self.mins)) * 60 + 90 - int(
                    str(datetime.now()).split()[1].split(":")[2].split('.')[0])
                print(f"Weekend：Sleep till tmr 03:00. Now is {self.weekday+1}")
                logger.info(f"Weekend：Sleep till tmr 03:00. Now is {self.weekday+1}")
                time.sleep(sleepTime)
                print(str(datetime.now()))
                self.nextLoop = True
                return 0

    # check market pause:
    def check_market_pause(self):
        self.refresh_time()
        if (int(self.hour) < 9 and int(self.hour) >= 3) or (int(self.hour) == 2 and int(self.mins) >= 46):
            waittingTime = datetime.strptime(str("{}:{}:10".format(9, 40)), "%H:%M:%S") - datetime.strptime(
                str("{}:{}:{}".format(str(self.hour), str(self.mins), str(self.second))), "%H:%M:%S")
            print("Start at {}:{}".format(9, 40))
            logger.info("Market Pause - Start at {}:{}".format(9, 40))
            time.sleep(int(waittingTime.seconds))
            print(str(datetime.now()))
            self.nextLoop = True
            return 0
        elif int(self.hour) == 12 or (int(self.hour) == 11 and int(self.mins) >= 46):
            waittingTime = datetime.strptime(str("{}:{}:10".format(13, 10)), "%H:%M:%S") - datetime.strptime(
                str("{}:{}:{}".format(str(self.hour), str(self.mins), str(self.second))), "%H:%M:%S")
            print("Start at {}:{}".format(13, 10))
            logger.info("Market Pause - Start at {}:{}".format(9, 40))
            time.sleep(int(waittingTime.seconds))
            print(str(datetime.now()))
            self.nextLoop = True
            return 0
        elif (int(self.hour) == 16 and int(self.mins) >= 30) or (int(self.hour) == 16 and int(self.mins) >= 16):
            waittingTime = datetime.strptime(str("{}:{}:10".format(17, 25)), "%H:%M:%S") - datetime.strptime(
                str("{}:{}:{}".format(str(self.hour), str(self.mins), str(self.second))), "%H:%M:%S")
            print("Start at {}:{}".format(17, 25))
            logger.info("Market Pause - Start at {}:{}".format(17, 25))
            time.sleep(int(waittingTime.seconds))
            print(str(datetime.now()))
            self.nextLoop = True
            return 0

    # check data pause:
    def check_data_pause(self):
        self.refresh_time()
        if int(self.mins) % 15 < 14:
            sleepTime = (14 - int(self.mins) % 15 ) * 60  - int(
                str(datetime.now()).split()[1].split(":")[2].split('.')[0]) + 5
            time.sleep(sleepTime)
        sleepTime1 = 60 - int(
            str(datetime.now()).split()[1].split(":")[2].split('.')[0]) -1
        if sleepTime1>1:
            time.sleep(sleepTime1)
        else:
            time.sleep(15*60)

    def check_accident(self):
        self.refresh_time()
        if int(self.hour) <= 12:
            waittingTime = datetime.strptime(str("{}:{}:10".format(13, 10)), "%H:%M:%S") - datetime.strptime(
                str("{}:{}:{}".format(str(self.hour), str(self.mins), str(self.second))), "%H:%M:%S")
            print("Accident, trade will Start at {}:{}".format(13, 10))
            logger.info("Accident, trade will Start at {}:{}".format(13, 10))
            time.sleep(int(waittingTime.seconds))
            print(str(datetime.now()))
            self.nextLoop = True
            return 0
        elif int(self.hour) <= 17:
            waittingTime = datetime.strptime(str("{}:{}:10".format(17, 25)), "%H:%M:%S") - datetime.strptime(
                str("{}:{}:{}".format(str(self.hour), str(self.mins), str(self.second))), "%H:%M:%S")
            print("Accident, trade will Start at {}:{}".format(17, 25))
            logger.info("Accident, trade will Start at {}:{}".format(17, 25))
            time.sleep(int(waittingTime.seconds))
            print(str(datetime.now()))
            self.nextLoop = True
            return 0
        elif int(self.hour) <= 24:
            waittingTime = datetime.strptime(str("{}:{}:10".format(23, 59)), "%H:%M:%S") - datetime.strptime(
                str("{}:{}:{}".format(str(self.hour), str(self.mins), str(self.second))), "%H:%M:%S")
            print("Accident, trade will Start at {}:{}".format(9, 40))
            logger.info("Accident, trade will Start at {}:{}".format(9, 40))
            time.sleep(int(waittingTime.seconds)+200)
            self.refresh_time()
            waittingTime = datetime.strptime(str("{}:{}:10".format(9, 40)), "%H:%M:%S") - datetime.strptime(
                str("{}:{}:{}".format(str(self.hour), str(self.mins), str(self.second))), "%H:%M:%S")
            time.sleep(int(waittingTime.seconds))
            print(str(datetime.now()))
            self.nextLoop = True
            return 0

    #check last trade status 
    def check_trade_status(self):
        self.hsicurrent_15min = self.hsicurrent["trade28_macd_20_25_15min"]
        self.last_hsicurrent_15min_data = list(self.hsicurrent_15min.find())[-1]
        if len(list(self.trade_history.find()))>0:
            last_trade_record = list(self.trade_history.find())[-1]
            if str(last_trade_record['buy'])=='1' and str(last_trade_record['sell'])=='1':
                self.sell=False
                self.buy=False
                self.firstTrade = True
            elif str(last_trade_record['buy'])=='1' and str(last_trade_record['sell'])=='0':
                can_sell_qty=1
                ret, data = self.trd_ctx.position_list_query(code=self.StockCode, pl_ratio_min=None, pl_ratio_max=None,
                                                        trd_env=TrdEnv.REAL, acc_id=0, acc_index=0, refresh_cache=False)
                if ret == RET_OK:
                    if data.shape[0] > 0:
                        can_sell_qty = int(data['can_sell_qty'][0])
                        print(f"Stock: {data['code'][0]} Remain QTY: {data['can_sell_qty'][0]}")
                        logger.info(f"Stock: {data['code'][0]} Remain QTY: {data['can_sell_qty'][0]}")
                else:
                    print('position_list_query error: ', data)
                    logger.info('position_list_query error: ', data)
                if can_sell_qty==1:
                    self.sell=False
                    self.buy=True
                    self.buy_status = last_trade_record['buy_status']
                    self.buy_price = last_trade_record['buy_price']
                else:
                    self.buy_time = ''
                    self.sell_time = ''
                    self.sell_price = ''
                    self.ema_20 = float(self.last_hsicurrent_15min_data['ema_20'])
                    self.ema_25 = float(self.last_hsicurrent_15min_data['ema_25'])
                    self.diff = float(self.last_hsicurrent_15min_data['diff_20_25'])
                    self.dea = float(self.last_hsicurrent_15min_data['dea_20_25'])
            else:
                print(f"Error in MongoDB record, Please Check Last Record:\n{last_trade_record}\n")
                logger.info(f"Error in MongoDB record, Please Check Last Record:\n{last_trade_record}\n")
                return 0
            self.buy_time = ''
            self.sell_time = ''
            self.sell_price = ''
            self.ema_20 = float(self.last_hsicurrent_15min_data['ema_20'])
            self.ema_25 = float(self.last_hsicurrent_15min_data['ema_25'])
            self.diff = float(self.last_hsicurrent_15min_data['diff_20_25'])
            self.dea = float(self.last_hsicurrent_15min_data['dea_20_25'])
            status = 'Done' if not self.buy else f'Processing. Buy Status: {self.buy_status}, Buy Price: {self.buy_price}'
            print(f"Last Trade Sell Time: {last_trade_record['sell_time']}\nOrder Status: {status}")
            logger.info(f"Last Trade Sell Time: {last_trade_record['sell_time']}\nOrder Status: {status}")
            self.trend = 'Up' if self.diff>self.dea else 'Down'
            print(f"\nTime:{self.last_hsicurrent_15min_data['time']} trend:{self.trend} Close:{self.last_hsicurrent_15min_data['close']} diff:{self.diff} dea:{self.dea}\n")
            logger.info(f"\nTime:{self.last_hsicurrent_15min_data['time']} trend:{self.trend} Close:{self.last_hsicurrent_15min_data['close']} diff:{self.diff} dea:{self.dea}\n")

    #update latest data from mongodb
    def refreshData(self):
        self.hsicurrent_15min = self.hsicurrent["trade28_macd_20_25_15min"]
        self.last_hsicurrent_15min_data = list(self.hsicurrent_15min.find())[-1]
        self.ema_20 = float(self.last_hsicurrent_15min_data['ema_20'])
        self.ema_25 = float(self.last_hsicurrent_15min_data['ema_25'])
        self.diff = float(self.last_hsicurrent_15min_data['diff_20_25'])
        self.dea = float(self.last_hsicurrent_15min_data['dea_20_25'])

    def buyIn(self):
        data = self.quote_ctx.get_market_snapshot([self.StockCode])
        try:
            close = float(str(data[1]['last_price']).split()[1])
        except Exception as e:
            time.sleep(1)
            data = self.quote_ctx.get_market_snapshot([self.StockCode])
            close = float(str(data[1]['last_price']).split()[1])
        self.buy_price = close
        self.buy_status = 'up'
        # self.trd_ctx.place_order(price=self.buy_price, qty=self.qty, code=self.StockCode,
        #                          trd_side=TrdSide.BUY)
        # time.sleep(1)
        # order_id = self.trd_ctx.order_list_query()[1]['order_id'].values.tolist()[-1]
        # qty = self.trd_ctx.order_list_query()[1]['qty'].values.tolist()[-1]
        # dealt_qty = self.trd_ctx.order_list_query()[1]['dealt_qty'].values.tolist()[-1]
        # print(self.buy_price)
        # while qty != dealt_qty:
        #     tempdata = self.quote_ctx.get_market_snapshot([self.StockCode])
        #     try:
        #         close = float(str(tempdata[1]['last_price']).split()[1])
        #     except Exception as e:
        #         print(e)
        #     try:
        #         self.trd_ctx.modify_order(ModifyOrderOp.NORMAL, price=int(close),
        #                                   qty=self.qty, order_id=order_id, acc_id=0,
        #                                   acc_index=0)
        #         print(close)
        #         time.sleep(1)
        #     except Exception as e:
        #         print(e)
        #     self.buy_price = int(close)
        #     dealt_qty = self.trd_ctx.order_list_query()[1]['dealt_qty'].values.tolist()[-1]
        insert_data = {
            'buy_time':self.timekey,
            'sell_time':"0",
            'buy':"1",
            'sell':"0",
            'buy_status':self.buy_status,
            'buy_price':str(close),
            'qty':str(self.qty),
        }
        self.buy_time = self.timekey
        self.trade_history.insert_one(insert_data)
        print('Time: {}; Buy Price: {} Buy Status: {}\n'.format(str(datetime.now()), self.buy_price,self.buy_status))
        logger.info('Time: {}; Buy Price: {} Buy Status: {}\n'.format(str(datetime.now()), self.buy_price,self.buy_status))

    def sellOut(self,):
        data = self.quote_ctx.get_market_snapshot([self.StockCode])
        try:
            close = float(str(data[1]['last_price']).split()[1])
        except Exception as e:
            time.sleep(1)
            data = self.quote_ctx.get_market_snapshot([self.StockCode])
            close = float(str(data[1]['last_price']).split()[1])
        self.sell_price = close
        # self.trd_ctx.place_order(price=self.sell_price, qty=self.qty, code=self.StockCode,
        #                          trd_side=TrdSide.SELL)
        # print(self.sell_price)
        # time.sleep(1)
        # order_id = self.trd_ctx.order_list_query()[1]['order_id'].values.tolist()[-1]
        # qty = self.trd_ctx.order_list_query()[1]['qty'].values.tolist()[-1]
        # dealt_qty = self.trd_ctx.order_list_query()[1]['dealt_qty'].values.tolist()[-1]
        # while qty != dealt_qty:
        #     close = close
        #     tempdata = self.quote_ctx.get_market_snapshot([self.StockCode])
        #     try:
        #         close = float(str(tempdata[1]['last_price']).split()[1])
        #     except Exception as e:
        #         print(e)
        #     try:
        #         self.trd_ctx.modify_order(ModifyOrderOp.NORMAL, price=int(close),
        #                                   qty=self.qty, order_id=order_id, acc_id=0,
        #                                   acc_index=0)
        #         print(close)
        #         time.sleep(1)
        #     except Exception as e:
        #         print(e)
        #     self.sell_price = int(close)
        #     dealt_qty = self.trd_ctx.order_list_query()[1]['dealt_qty'].values.tolist()[-1]
        if self.buy_status == 'up':
            self.benefit = (float(self.sell_price) - float(self.buy_price) - 2) * 10 * self.qty
        else:
            self.benefit = (float(self.buy_price) - float(self.sell_price) - 2) * 10 * self.qty
        self.sell_time = str(self.timekey)
        filter = {'buy_time': self.buy_time }
        update_value = {
            "$set": {
                'sell': '1',
                'sell_price': self.sell_price,
                'benefit': self.benefit,
                'sell_time': self.sell_time
            }
        }
        self.trade_history.update_one(filter=filter,update=update_value)
        print('\nTime: {}; Sell Price: {} Profit: {}\n'.format(str(datetime.now()), self.sell_price,
                                                              self.benefit))
        logger.info('\nTime: {}; Sell Price: {} Profit: {}\n'.format(str(datetime.now()), self.sell_price,self.benefit))

    def sellShort(self):
        data = self.quote_ctx.get_market_snapshot([self.StockCode])
        try:
            close = float(str(data[1]['last_price']).split()[1])
        except Exception as e:
            time.sleep(1)
            data = self.quote_ctx.get_market_snapshot([self.StockCode])
            close = float(str(data[1]['last_price']).split()[1])
        self.buy_price = close
        self.buy_status = 'down'
        # self.trd_ctx.place_order(price=self.buy_price, qty=self.qty, code=self.StockCode,
        #                          trd_side=TrdSide.SELL_SHORT)
        # print(self.sell_price)
        # time.sleep(1)
        # order_id = self.trd_ctx.order_list_query()[1]['order_id'].values.tolist()[-1]
        # qty = self.trd_ctx.order_list_query()[1]['qty'].values.tolist()[-1]
        # dealt_qty = self.trd_ctx.order_list_query()[1]['dealt_qty'].values.tolist()[-1]
        # while qty != dealt_qty:
        #     tempdata = self.quote_ctx.get_market_snapshot([self.StockCode])
        #     try:
        #         close = float(str(tempdata[1]['last_price']).split()[1])
        #     except Exception as e:
        #         print(e)
        #     try:
        #         self.trd_ctx.modify_order(ModifyOrderOp.NORMAL, price=int(close),
        #                                   qty=self.qty, order_id=order_id, acc_id=0,
        #                                   acc_index=0)
        #         print(close)
        #         time.sleep(1)
        #     except Exception as e:
        #         print(e)
        #     self.buy_price = int(close)
        #     dealt_qty = self.trd_ctx.order_list_query()[1]['dealt_qty'].values.tolist()[-1]
        self.buy_time = str(self.timekey[:-2]) + '00'
        insert_data = {
            'buy_time':self.buy_time,
            'sell_time':"0",
            'buy':"1",
            'sell':"0",
            'buy_status':self.buy_status,
            'buy_price':str(close),
            'qty':str(self.qty),
        }
        self.trade_history.insert_one(insert_data)
        print('Time: {}; Buy Price: {} Buy Status: {}\n'.format(str(datetime.now()), self.buy_price,self.buy_status))
        logger.info('Time: {}; Buy Price: {} Buy Status: {}\n'.format(str(datetime.now()), self.buy_price,self.buy_status))
    def buyBack(self, ):
        data = self.quote_ctx.get_market_snapshot([self.StockCode])
        try:
            close = float(str(data[1]['last_price']).split()[1])
        except Exception as e:
            time.sleep(1)
            data = self.quote_ctx.get_market_snapshot([self.StockCode])
            close = float(str(data[1]['last_price']).split()[1])
        # self.trd_ctx.place_order(price=self.sell_price, qty=self.qty, code=self.StockCode,
        #                          trd_side=TrdSide.BUY_BACK)
        # print(self.sell_price)
        # time.sleep(1)
        # order_id = self.trd_ctx.order_list_query()[1]['order_id'].values.tolist()[-1]
        # qty = self.trd_ctx.order_list_query()[1]['qty'].values.tolist()[-1]
        # dealt_qty = self.trd_ctx.order_list_query()[1]['dealt_qty'].values.tolist()[-1]
        # while qty != dealt_qty:
        #     tempdata = self.quote_ctx.get_market_snapshot([self.StockCode])
        #     try:
        #         close = float(str(tempdata[1]['last_price']).split()[1])
        #     except Exception as e:
        #         print(e)
        #     try:
        #         self.trd_ctx.modify_order(ModifyOrderOp.NORMAL, price=int(close),
        #                                   qty=self.qty, order_id=order_id, acc_id=0,
        #                                   acc_index=0)
        #         print(close)
        #         time.sleep(1)
        #     except Exception as e:
        #         print(e)
        #     self.sell_price = int(close)
        #     dealt_qty = self.trd_ctx.order_list_query()[1]['dealt_qty'].values.tolist()[-1]
        self.sell_price = close
        if self.buy_status == 'up':
            self.benefit = (float(self.sell_price) - float(self.buy_price) - 2) * 10 * self.qty
        else:
            self.benefit = (float(self.buy_price) - float(self.sell_price) - 2) * 10 * self.qty
        self.sell_time = str(self.timekey[:-2])+'00'
        filter = {'buy_time': self.buy_time }
        update_value = {
            "$set": {
                'sell': '1',
                'sell_price': self.sell_price,
                'benefit': self.benefit,
                'sell_time': self.sell_time
            }
        }
        self.trade_history.update_one(filter=filter,update=update_value)
        print('Time: {}; Sell Price: {} Profit: {}\n'.format(str(datetime.now()), self.sell_price,self.benefit))
        logger.info('Time: {}; Sell Price: {} Profit: {}\n'.format(str(datetime.now()), self.sell_price,self.benefit))

    def get_StockCode(self):
        today = str(datetime.now()).split()[0].split("-")
        year = today[0][-2:]
        month = today[1]
        day = today[2]
        weekday = datetime.now().weekday()
        month_days = {
            '01':31,
            '02':28,
            '03':31,
            '04':30,
            '05':31,
            '06':30,
            '07':31,
            '08':31,
            '09':30,
            '10':31,
            '11':30,
            '12':31
        }
        next_month = str(int(month)+1) if int(month)<12 else '01'
        futureday = datetime.strptime('01'+'/'+str(next_month)+'/'+year, '%d/%m/%y').weekday()
        if futureday==1 and weekday>=4 and int(day)>=month_days[month]-4:
            if next_month=='01':
                next_year = str(int(year)+1)
                stockCode =  self.StockCodeHeader+next_year+next_month
            else:
                next_month = next_month if int(next_month)>9 else '0'+next_month
                stockCode =  self.StockCodeHeader+year+next_month
        elif (futureday==5 or futureday==6 or futureday==0) and weekday>=3 and int(day)>=month_days[month]-4:
            if next_month=='01':
                next_year = str(int(year)+1)
                stockCode =  self.StockCodeHeader+next_year+next_month
            else:
                stockCode =  self.StockCodeHeader+year+next_month
        elif int(day)>=month_days[month]-1:
            if next_month=='01':
                next_year = str(int(year)+1)
                stockCode =  self.StockCodeHeader+next_year+next_month
            else:
                next_month = next_month if int(next_month)>9 else '0'+next_month
                stockCode =  self.StockCodeHeader+year+next_month
        else:
            return self.StockCodeHeader + year + month
        return stockCode


if __name__ == '__main__':
    a = HSI_strategy()