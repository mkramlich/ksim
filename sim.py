#!/usr/bin/env python3

'''
ksim: a restaurant delivery sim (as a low-fidelity, proof-of-concept spike)
by Mike Kramlich, groglogic@gmail.com, 2020 May 19
'''

from json      import load as json_load
import logging
from logging   import DEBUG, INFO, ERROR
from random    import uniform
from queue     import PriorityQueue, Queue
import sys
from threading import current_thread, Thread, Timer
from time      import sleep, time

SINGLE_TEMPS   = ('hot', 'cold', 'frozen')

SHUTDOWN_P     = float('inf') # makes shutdown event lowest priority so all other events processed first
TEMPORAL_P     = -1           # priority field ignored in temporal mode. prefer consistency

cfg            = None         # config dict. loads config.py first/always, then updates by sys argv config file. tests can override last
ot             = None         # top-level for testing only
kt             = None         # top-level for testing only
simu_time_span = None         # top-level for testing only


class OrderingThread(Thread):
    def __init__(self, kitchenQ, now, **kwargs):
        Thread.__init__(self, name='OT', **kwargs)

        self.kitchenQ  = kitchenQ
        self.started   = None
        self.now       = now
        self.exception = None

    def run(self):
        try:
            self.started = self.now = self.time()
            self.log(INFO, 'started')
            if cfg['order_rate'] <= 0:
                self.log(INFO, 'order_rate <= 0, will not place orders')
            else:
                approx_flag = (cfg['concurrency'] == 'temporal') and '~' or ''
                orders = self.read_orders()
                for o, order in enumerate(orders, 1):
                    now = self.time()
                    timerel = now - self.started
                    pause_between_orders = (cfg['order_rate'] == float('inf')) and 0 or (1.0 / cfg['order_rate'])
                    ot = now
                    p = (cfg['concurrency'] == 'temporal') and TEMPORAL_P or ot
                    new_kqueue_size = self.kitchenQ.qsize() + 1 # estimate. not strictly guaranteed to always be correct. due to KT and OT threads running concurrently, producing into and consuming out of the same queue in parallel

                    self.log(INFO, 'placed order: %i, %s, %s, new kqueue ~%i, now %f/+%f, order %s%f/+%f' % (o, order['id'], order['name'], new_kqueue_size, now, timerel, approx_flag, ot, ot-self.started))
                    self.kitchenQ.put((p, ('order_received', o, order))) #TODO add counter here of orders-submitted?
                    #if o == 2: break #TODO make this a devtest feature via config or main/sys args
                    if o < len(orders): # don't add a pause or time gap if this was the last order
                        if cfg['concurrency'] == 'temporal': sleep(pause_between_orders)
                        else: self.now += pause_between_orders # priority
            self.log(INFO, 'exits')
        except BaseException as ex:
            self.exception = ex
            logging.exception(ex) #TODO 1-line. app log format
            raise

    def read_orders(self): #TODO refactor from all-at-once to iterable/stream
        if cfg['orders_literal'] is not None: # in case they were injected by a test
            self.log(INFO, 'cfg.orders_literal will be used instead of cfg.orders_file')
            data = cfg['orders_literal']
        else: # normal case
            data = None
            with open(cfg['orders_file']) as f:
                data = json_load(f)

        #self.log(DEBUG, json.dumps(data,indent=2))
        self.log(INFO, 'total orders to place: %i' % len(data))
        return data

    def time(self):
        return cfg['concurrency'] == 'temporal' and time() or self.now

    def log(self, level, message, *args, **kwargs):
        timerel = self.time() - self.started # real time only in temporal mode; in priority mode its a simulated time diff
        log(level, "+%5.6f:  %s" % (timerel,message), *args, **kwargs)


class KitchenThread(Thread):
    def __init__(self, now, **kwargs):
        Thread.__init__(self, name='KT', **kwargs)

        self.should_run = True
        self.started    = None
        self.now        = now
        self.exception  = None

        if cfg['concurrency'] == 'temporal':
            self.q = Queue()         # threadsafe unbounded FIFO
        else: # priority
            self.q = PriorityQueue() # threadsafe unbounded priority

        sns = list(SINGLE_TEMPS)
        sns.append('overflow')
        self.shelf_names = tuple(sns)

        self.shelves = {} # orders ready for delivery pickup by couriers, by shelf
        for sn in self.shelf_names:
            self.shelves[sn] = []

        self.peaks   = {} # peak count of orders, by shelf
        for sn in self.shelf_names:
            self.peaks[sn] = 0

        self.order_ready      = {}    # key is oid. value is float timestamp when became ready to eat/pickup
        self.order_locs       = {}    # key is oid. value is shelf name if on a shelf, or, capdrop or wasted
        self.capacity_dropped = []    # all capdropped orders
        self.wasted           = []    # orders too old/stale for quality delivery
        self.courier_timers   = set() # all couriers who have been dispatched but not yet arrived for pickup
        self.courier_arrivals = {}    # key is oid. value is float timestamp when the order's courier arrived
        self.counts = {
            'events'                  : 0,
            'unhand'                  : 0,
            'event:order_received'    : 0,
            'noshelf'                 : 0,
            'ordercheck_wasted'       : 0,
            'couriers_dispatched'     : 0,
            'event:courier_arrived'   : 0,
            'pickupfail_capdrop'      : 0,
            'pickupfail_wasted_prior' : 0,
            'pickupfail_wasted_now'   : 0,
            'pickupfail_badloc'       : 0,
            'orders_delivered'        : 0,
            'event:shutdown'          : 0}

    def run(self):
        try:
            self.started = self.now = self.time()
            self.log(INFO, 'started')
            while self.should_run \
                or self.q.qsize() \
                or len(self.courier_timers):
                event = self.q.get()
                self.handle_event(event)
                self.q.task_done()
            self.log(INFO, 'exits')
        except BaseException as ex:
            self.exception = ex
            logging.exception(ex) #TODO 1-line. app log format
            raise

    def handle_event(self, event):
        self.counts['events'] += 1

        # the 1st field of the event represents priority.
        # used by PriorityQueue to rank entries & simulate correct temporal order of events.
        # it is ignored in temporal mode and not used by Queue but populated for consistency.
        # look at the impl of self.time() to better understand why we do the assignment below
        p = event[0]
        if p != SHUTDOWN_P:
            self.now = (cfg['concurrency'] == 'temporal') and time() or p

        etype = event[1][0]

        self.counts['event:'+etype] += 1

        self.log(INFO, 'kitchen handle_event: %s' % str(event))
        self.status()

        if   etype == 'shutdown':
            self.should_run = False
            self.log(DEBUG, 'kitchen thread will stop when queue and timers reach 0')
        elif etype == 'order_received':
            self.handle_order_received(event)
        elif etype == 'courier_arrived':
            self.handle_courier_arrived(event)
        else:
            self.log(ERROR, 'unhandled kitchen event: %s' % etype)
            self.counts['unhand'] += 1

    def handle_order_received(self, event):
        etype = event[1][0]
        pos   = event[1][1] # position within original orders input batch; 1-based since only human-read
        order = event[1][2] #TODO consider cloning it so more threadsafe

        if cfg['courier_dispatch_enabled']:
            self.dispatch_courier(etype,pos,order) # upon receiving order, kitchen immed dispatches courier to pickup & deliver specific order

        oid                  = order['id']        # uuid (eg. "0ff534a7-a7c4-48ad-b6ec-7632e36af950")
        name                 = order['name']      # like Cheese Pizza
        temp                 = order['temp']      # Preferred shelf storage temperature (possible: cold, frozen, hot)
        shelf_life           = order['shelfLife'] # Shelf wait max duration (seconds)
        decay_rate           = order['decayRate'] # float fraction value as deterioration modifier
        shelf_decay_modifier = 1.0                # assume normal until we know what shelf it ends up on

        now = self.time()
        self.order_ready[oid] = now
        order_age = 0
        ovalue = order_value(order_age, shelf_life, decay_rate, shelf_decay_modifier) # should always be 1.0 here but nice to log

        self.log(INFO, 'kitchen prepares order instantly, ready: order %i, %s, time %f, value %f' % (pos, oid, now, ovalue))

        self.check_orders_to_waste(now)

        if temp not in self.shelves:
            self.log(ERROR, 'order has no shelf for temp, no save: order %i, %s, %s' % (pos, oid, temp))
            self.counts['noshelf'] += 1 #TODO if case can happen, also handle right downstream in handle_courier_arrived
            return

        if self.is_shelf_avail(temp): # if an order's ideal temp shelf has space, put it there
            self.add_order_to_shelf(order,temp)
            self.log(INFO, 'order added to ideal temp shelf: order %i, %s, %s' % (pos, oid, temp))
            return

        if cfg['shelf_capacity']['overflow'] < 1:
            self.capacity_dropped.append(order)
            self.order_locs[oid] = 'capdrop'
            self.log(INFO, 'dropped new order because zero overflow capacity: order %i, %s, %s' % (pos, oid, temp))
            return

        if self.is_shelf_avail('overflow'): # otherwise, if overflow has space, put it there
            self.add_order_to_shelf(order,'overflow')
            self.log(INFO, 'order added to overflow shelf: order %i, %s, %s' % (pos, oid, temp))
            return

        # try to free space on overflow shelf by moving orders from there to their ideal temp shelf
        os = list(self.shelves['overflow'])
        for o in os:
            t = o['temp']
            if self.is_shelf_avail(t): # this overflow order's ideal temp shelf has space so move it there
                self.shelves['overflow'].remove(o)
                self.add_order_to_shelf(o,t)
                self.log(INFO, 'order moved from overflow to ideal temp shelf: %s' % o)

        if self.is_shelf_avail('overflow'):
            self.add_order_to_shelf(order,'overflow')
            self.log(INFO, 'order added to newly free overflow shelf: order %i, %s, %s' % (pos, oid, temp))
            return

        # if overflow still isn't avail, then pick an order from it and discard, then place new order there

        dropped_order = self.shelves['overflow'][0] #TODO non-ideal. better to pick order with least current value, eg.

        self.shelves['overflow'].remove(dropped_order)
        self.capacity_dropped.append(dropped_order)
        self.order_locs[dropped_order['id']] = 'capdrop'

        self.add_order_to_shelf(order,'overflow') # new order is ready to pickup, but on the overflow shelf

        self.log(INFO, 'dropped overflow order to make room for new: order %i, new %s, dropped %s' % (pos, order, dropped_order))

    def dispatch_courier(self, etype, pos, order):
        courier_arrival_delay = uniform(cfg['courier_arrival_min'], cfg['courier_arrival_max'])
        oid = order['id']
        arrival_time_approx = self.time() + courier_arrival_delay
        orig_order_event = (etype, pos, order)
        ct = self.prepare_courier_timer(oid, courier_arrival_delay, arrival_time_approx, orig_order_event)
        self.courier_timers.add(ct)
        self.counts['couriers_dispatched'] += 1
        approx_flag = (cfg['concurrency'] == 'temporal') and '~' or ''
        self.log(INFO, 'dispatching courier: order %i, %s, new ctimers %i, arrive %s%f/+%f' % (pos, oid, len(self.courier_timers), approx_flag, arrival_time_approx, courier_arrival_delay))
        self.start_courier_timer(ct, arrival_time_approx, orig_order_event)

    def prepare_courier_timer(self, oid, courier_arrival_delay, arrival_time_approx, orig_order_event):
        if cfg['concurrency'] == 'temporal':
            timer = Timer(courier_arrival_delay, courier_arrives, (arrival_time_approx,self.q,orig_order_event))
            timer.setName('CT') # technically there will be 1+ distinct threads, each with name CT, but keeps log simpler
            return timer
        else: # priority
            return 'courier_timer|%s' % oid

    def start_courier_timer(self, courier_timer, arrival_time_approx, orig_order_event):
        if cfg['concurrency'] == 'temporal':
            courier_timer.start()
        else: # priority
            p = arrival_time_approx
            self.q.put((p, ('courier_arrived', courier_timer, orig_order_event)))

    def handle_courier_arrived(self, event):
        self.log(INFO, 'kitchen handle_courier_arrived: %s' % str(event))
        now = self.time()

        courier_timer    = event[1][1]
        orig_order_event = event[1][2]
        order_pos        = orig_order_event[1]
        order            = orig_order_event[2]

        self.courier_timers.remove(courier_timer)
        self.log(DEBUG, 'courier_timers size down to %i' % len(self.courier_timers))

        oid                  = order['id']
        loc                  = self.order_locs[oid]
        order_age            = now - self.order_ready[oid]
        shelf_life           = order['shelfLife']
        decay_rate           = order['decayRate']
        shelf_decay_modifier = self.get_shelf_decay_modifier(loc)
        ovalue               = order_value(order_age, shelf_life, decay_rate, shelf_decay_modifier)

        self.courier_arrivals[oid] = now

        if loc == 'capdrop':
            self.counts['pickupfail_capdrop'] += 1
            self.log(INFO, "courier cannot pickup because order capdropped: order %i, %s" % (order_pos, order))
        elif loc == 'wasted':
            self.counts['pickupfail_wasted_prior'] += 1
            self.log(INFO, 'courier wont pickup/deliver, order wasted prior: order %i, %s, now %f, age %f, value %f' % (order_pos, order, now, order_age, ovalue))
        elif loc in self.shelves:
            shelf = self.shelves[loc]
            shelf.remove(order)
            if ovalue <= 0:
                self.wasted.append(order)
                self.order_locs[oid] = 'wasted'
                self.counts['pickupfail_wasted_now'] += 1
                self.log(INFO, 'courier wont pickup/deliver, order too old, now wasted: order %i, %s, now %f, age %f, value %f' % (order_pos, order, now, order_age, ovalue))
            else:
                self.counts['orders_delivered'] += 1
                self.log(INFO, 'courier picks up, instantly delivers: order %i, %s, now %f, age %f, value %f' % (order_pos, order, now, order_age, ovalue)) 
        else:
            self.counts['pickupfail_badloc'] += 1
            self.log(ERROR, 'courier cannot pickup because badloc: %s, %s' % (loc, order))

    def check_orders_to_waste(self, now):
        self.log(DEBUG, 'check_orders_to_waste')
        # check if any orders on shelf are so old they should be considered undeliverable
        # if so, move them from their shelf to waste
        for t in self.shelf_names:
            shelf = self.shelves[t]
            for o in shelf:
                age = now - self.order_ready[o['id']]
                self.log(INFO, 'waste check: %s, age %f, value %f' % (o, age, self.order_value(o,now)))
            to_waste = [o for o in shelf if self.order_value(o,now) <= 0]
            for o in to_waste:
                oid = o['id']
                ready = self.order_ready[oid]
                ov = self.order_value(o,now)
                shelf.remove(o)
                self.wasted.append(o)
                self.order_locs[oid] = 'wasted'
                self.counts['ordercheck_wasted'] += 1
                self.log(INFO, "shelved order old, should be waste: %s, shelf %s, now %f/+%f, ready %f/+%f, age %f, value %f" %
                    (o, t, now, now-self.started, ready, ready-self.started, now-ready, ov))

    def add_order_to_shelf(self, order, shelfname):
        self.shelves[shelfname].append(order)
        self.order_locs[order['id']] = shelfname
        self.update_peak(shelfname)

    def is_shelf_full(self, name):
        return not self.is_shelf_avail(name)

    def is_shelf_avail(self, name):
        return len(self.shelves[name]) < cfg['shelf_capacity'][name]

    def update_peak(self, shelf_name):
        if len(self.shelves[shelf_name]) > self.peaks[shelf_name]:
            self.peaks[shelf_name] = len(self.shelves[shelf_name])

    def get_shelf_decay_modifier(self, loc):
        return (loc in SINGLE_TEMPS) and 1.0 or 2.0

    def order_value(self, order, now):
        oid                  = order['id']
        order_age            = now - self.order_ready[oid]
        shelf_life           = order['shelfLife']
        decay_rate           = order['decayRate']
        loc                  = self.order_locs[oid]
        shelf_decay_modifier = self.get_shelf_decay_modifier(loc)
        return order_value(order_age, shelf_life, decay_rate, shelf_decay_modifier)

    def time(self):
        return cfg['concurrency'] == 'temporal' and time() or self.now

    def status(self):
        now = self.time()
        #timerel = self.started and (now - self.started) or 0.0
        self.log(INFO, 'STATUS otlife %i-%i-%i, ktlife %i-%i-%i-%i, kqueue %i, ctasks %i, hot %i/%i/%s, cold %i/%i/%s, frozen %i/%i/%s, overflow %i/%i/%s, noshelf %i, capdrops %i, wasted %i, ocheckw %i, events %i, unhand %i, orders %i, oready %i, cdispatch %i, carrive %i, pfailcd %i, pfailwap %i, pfailwan %i, pfailbl %i, deliver %i' %
            ((ot.started is not None) and 1 or 0,     # was OT ever started? 1 if yes. 0 if no
             ot.is_alive() and 1 or 0,                # is OT running now?   (ditto above)
             (ot.exception is not None) and 1 or 0,   # did OT stop due to an exception?
             (self.started is not None) and 1 or 0,   # was KT ever started?
             self.is_alive() and 1 or 0,              # is KT running now?
             (self.exception is not None) and 1 or 0, # did KT stop due to an exception?
             self.counts['event:shutdown'],           # did KT receive a shutdown event? how many?
             self.q.qsize(),
             len(self.courier_timers),
             len(self.shelves['hot']),
             self.peaks['hot'],
             cfg['shelf_capacity']['hot'],
             len(self.shelves['cold']),
             self.peaks['cold'],
             cfg['shelf_capacity']['cold'],
             len(self.shelves['frozen']),
             self.peaks['frozen'],
             cfg['shelf_capacity']['frozen'],
             len(self.shelves['overflow']),
             self.peaks['overflow'],
             cfg['shelf_capacity']['overflow'],
             self.counts['noshelf'],
             len(self.capacity_dropped),
             len(self.wasted),
             self.counts['ordercheck_wasted'],
             self.counts['events'],
             self.counts['unhand'],
             self.counts['event:order_received'],
             len(self.order_ready),
             self.counts['couriers_dispatched'],
             self.counts['event:courier_arrived'],
             self.counts['pickupfail_capdrop'],
             self.counts['pickupfail_wasted_prior'],
             self.counts['pickupfail_wasted_now'],
             self.counts['pickupfail_badloc'],
             self.counts['orders_delivered']))
        self.log_shelves(now)

    def log_shelves(self, now):
        for k in self.shelf_names:
            if not len(self.shelves[k]): continue
            os = ("%s %f" % (o['id'],self.order_value(o,now)) for o in self.shelves[k])
            s = ', '.join(os)
            self.log(INFO, "shelf %-8s: %s" % (k,s))

    def log(self, level, message, *args, **kwargs):
        now = self.time()
        timerel = self.started and (now - self.started) or 0 # real time only in temporal mode; in priority mode its a simulated time diff
        log(level, "+%5.6f:  %s" % (timerel,message), *args, **kwargs)


def log(level, message, *args, **kwargs):
    #print(message, *args, **kwargs)
    logging.log(level, message, *args, **kwargs)

def log_mt(level, message, *args, **kwargs):
    log(level, "            :  %s" % message)

def courier_arrives(arrival_time_approx, kitchenQ, orig_order_event):
    # only used in temporal concurrency mode. only called by a KT-started courier Timer
    #TODO consider making method of KT
    courier_timer = current_thread()
    now = time()
    time_span = now - kt.started #TODO this is not ideal way but close enough
    log(INFO, '+%5.6f:  courier_arrives: thread %s, order %i, %s' % (time_span, courier_timer, orig_order_event[1], orig_order_event[2]['id']))
    kitchenQ.put((TEMPORAL_P,('courier_arrived', courier_timer, orig_order_event)))

def order_value(order_age, shelf_life, decay_rate, shelf_decay_modifier):
    decay              = order_age * decay_rate * shelf_decay_modifier
    shelf_life_decayed = float(shelf_life) - decay
    return shelf_life_decayed / shelf_life

def configure(*args, **kwargs):
    global cfg

    current_thread().setName('MT') # non-ideal but lesser evil for logs; configure intended to be called only by a main thread

    logging.basicConfig(stream=sys.stdout, format='%(levelname)-5s %(threadName)s: %(message)s', level=logging.INFO)

    log_mt(INFO, '; '.join(__doc__.strip().split('\n'))) # banner at log start

    log_mt(INFO, 'sys.argv: %s'         % sys.argv)
    log_mt(INFO, 'config fn args: %s'   % str(args))
    log_mt(INFO, 'config fn kwargs: %s' % kwargs)

    base_config = './config.py'
    log_mt(INFO, 'loading base config: %s' % base_config)
    with open(base_config) as f:
        cfg = eval(f.read())

    config2 = None

    if len(sys.argv) > 1:
        config2 = sys.argv[1] #TODO non-ideal, but not an actual issue at present

    if len(args) > 0:
        config2 = args[0]

    if config2:
        log_mt(INFO, 'config will update from: %s' % config2)
        #TODO if not found try again looking in configs/*
        with open(config2) as f:
            cfg2 = eval(f.read())
            cfg.update(cfg2)

    if 'concurrency' in kwargs: #TODO add support for every other config param
        log_mt(INFO, 'config will update from kwargs: concurrency = %s' % kwargs['concurrency'])
        cfg['concurrency'] = kwargs['concurrency']

def log_cfg():
    cfg2log = cfg
    if not cfg['log_config_large_orders_literal'] and cfg['orders_literal'] and len(cfg['orders_literal']) > 10:
        cfg2log = dict(cfg)
        ol_len = len(cfg2log['orders_literal'])
        cfg2log['orders_literal'] = '[...orders not shown due to log_config_large_orders_literal off (array size %i)...]' % ol_len
    
    log_mt(INFO, 'cfg: %s' % cfg2log)

def run():
    global ot, kt, simu_time_span

    started = time()

    log_cfg()

    kt = KitchenThread(started) # has the only event queue. only consumer. some producing
    ot = OrderingThread(kt.q,started) # producer-only

    kt.status()

    if cfg['concurrency'] == 'temporal':
        kt.start()
        ot.start()
        ot.join() # wait til all orders submitted, or OT dies
        priority = TEMPORAL_P # priority field ignored in temporal mode. prefer consistency
    else: # priority
        ot.start()
        ot.join() # wait til all orders submitted, or OT dies
        kt.start()
        priority = SHUTDOWN_P

    kt.q.put((priority,('shutdown',)))

    kt.join() # wait til all events/tasks done, or KT dies

    kt.status() # note that we only call KT's status method from MT when we know KT and OT are not running

    ended                              = time()
    real_time_span                     = ended - started
    simu_time_span                     = kt.now - kt.started
    log_mt(INFO, 'simu time span: %fs' % simu_time_span)
    log_mt(INFO, 'real time span: %fs' % real_time_span)

def main(*args, **kwargs):
    configure(*args,**kwargs)
    run()

if __name__ == '__main__':
    main()
