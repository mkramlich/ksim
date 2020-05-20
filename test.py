#!/usr/bin/env python3

from importlib import reload
import logging
import sys
from threading import current_thread
from time import time
from unittest import main, TestCase
from uuid import uuid4

conc_map =  {'P':'priority', 'T':'temporal'}

example_order = {'id':        'cbfe326f-661c-4ced-ae4a-c83b5ed60a01',
                 'name':      "Logan's Rum",
                 'temp':      'cold',
                 'shelfLife': 100,
                 'decayRate': 50} 

def gen_unique_order(shelf_life=None, decay_rate=None, temp=None):
    o = dict(example_order)
    o['id'] = uuid4()
    if shelf_life is not None: o['shelfLife'] = shelf_life
    if decay_rate is not None: o['decayRate'] = decay_rate
    if temp is not None:       o['temp'] = temp
    return o


# the leading letter of a class name (like A in A_TestBasic) is used to ensure the order of test execution
# alpha by TestCase subclass names
# within a TestCase, test method names use a similar technique (test_A_moo will be called before test_B_foo)

class A_TestBasic(TestCase):
    def test_import(self):
        log(type(self).__name__ + '.test_import()')
        log('sys.argv: %s' % sys.argv)
        import sim
        reload(sim)
        self.assertTrue(True) # to check that the sim imported with no exceptions

    def test_config(self):
        log(type(self).__name__ + '.test_config()')
        import sim
        reload(sim)
        sim.configure()
        self.assertTrue(True) # to check that the sim's configure ran without exceptions


class B_TestBasic(TestCase): # like A_TestBasic but meant to have a subclass variant of its tests for every concurrency type
    concurrency = 'P' # priority

    def test_A_config2(self):
        log(type(self).__name__ + '.test_A_config2()')
        import sim
        reload(sim)
        sim.configure('configs/config-%s-2-2-6-10-10-10-15-orders.py' % self.concurrency)

        self.assertEqual(sim.cfg['concurrency'],                     conc_map[self.concurrency])
        self.assertEqual(sim.cfg['order_rate'],                      2.0)
        self.assertEqual(sim.cfg['courier_arrival_min'],             2.0)
        self.assertEqual(sim.cfg['courier_arrival_max'],             6.0)
        self.assertEqual(sim.cfg['shelf_capacity']['hot'],           10)
        self.assertEqual(sim.cfg['shelf_capacity']['cold'],          10)
        self.assertEqual(sim.cfg['shelf_capacity']['frozen'],        10)
        self.assertEqual(sim.cfg['shelf_capacity']['overflow'],      15)
        self.assertEqual(sim.cfg['orders_file'],                     'orders.json')
        self.assertEqual(sim.cfg['orders_literal'],                  None)
        self.assertEqual(sim.cfg['courier_dispatch_enabled'],        True)
        #NOTE we don't assert the state of log_config_large_orders_literal config because not in the overlay config file

    def assertRange(self, value, min, max):
        self.assertGreaterEqual(value, min)
        self.assertLessEqual(value, max)

    def test_B_default_scenario_outcome(self):
        log(type(self).__name__ + '.test_B_default_scenario_outcome()')
        import sim
        reload(sim)
        sim.main('configs/config-%s-2-2-6-10-10-10-15-orders.py' % self.concurrency)

        orders     = 132 # we know there are this many orders in the JSON file configured
        order_rate = 2.0
        ca_max     = 6.0

        self.assertTrue(sim.cfg['order_rate'],          order_rate)
        self.assertTrue(sim.cfg['courier_arrival_max'], ca_max)

        self.assertTrue(sim.ot.started is not None)
        self.assertTrue(not sim.ot.is_alive())
        self.assertTrue(sim.ot.exception is None)
        self.assertTrue(sim.kt.started is not None)
        self.assertTrue(not sim.kt.is_alive())
        self.assertTrue(sim.kt.exception is None)
        self.assertEqual(sim.kt.counts['event:shutdown'],          1)

        self.assertEqual(sim.kt.q.qsize(),                         0)
        self.assertEqual(len(sim.kt.courier_timers),               0)

        self.assertEqual(len(sim.kt.shelves['hot']),               0)
        self.assertRange(sim.kt.peaks['hot'],                      5, 7)
        self.assertEqual(sim.cfg['shelf_capacity']['hot'],         10)
        self.assertEqual(len(sim.kt.shelves['cold']),              0)
        self.assertRange(sim.kt.peaks['cold'],                     5, 7)
        self.assertEqual(sim.cfg['shelf_capacity']['cold'],        10)
        self.assertEqual(len(sim.kt.shelves['frozen']),            0)
        self.assertRange(sim.kt.peaks['frozen'],                   5, 7)
        self.assertEqual(sim.cfg['shelf_capacity']['frozen'],      10)
        self.assertEqual(len(sim.kt.shelves['overflow']),          0)
        self.assertEqual(sim.kt.peaks['overflow'],                 0)
        self.assertEqual(sim.cfg['shelf_capacity']['overflow'],    15)

        self.assertEqual(sim.kt.counts['noshelf'],                 0)
        self.assertEqual(len(sim.kt.capacity_dropped),             0)
        self.assertEqual(len(sim.kt.wasted),                       0)
        self.assertEqual(sim.kt.counts['ordercheck_wasted'],       0)

        events = (orders * 2) + 1 # should be 265. because 132 order_received, 132 courier_arrived, 1 shutdown
        self.assertEqual(events,                                   265) # can't hurt to check
        self.assertEqual(sim.kt.counts['events'],                  events)
        self.assertEqual(sim.kt.counts['unhand'],                  0)
        self.assertEqual(sim.kt.counts['event:order_received'],    orders)
        self.assertEqual(len(sim.kt.order_ready),                  orders)
        self.assertEqual(sim.kt.counts['couriers_dispatched'],     orders)
        self.assertEqual(sim.kt.counts['event:courier_arrived'],   orders)

        self.assertEqual(sim.kt.counts['pickupfail_capdrop'],      0)
        self.assertEqual(sim.kt.counts['pickupfail_wasted_prior'], 0)
        self.assertEqual(sim.kt.counts['pickupfail_wasted_now'],   0)
        self.assertEqual(sim.kt.counts['pickupfail_badloc'],       0)
        self.assertEqual(sim.kt.counts['orders_delivered'],        orders)

        if self.concurrency == 'P': # because we can only guarantee this upper bound in priority mode:
            simu_time_span_max = ((orders-1) / order_rate) + ca_max # should be 71.5
            self.assertEqual(simu_time_span_max,     71.5)          # can't hurt to check our math
            self.assertLessEqual(sim.simu_time_span, simu_time_span_max) # important for correctness of priority mode

    def test_C_order_added_to_temp_shelf(self):
        log(type(self).__name__ + '.test_C_order_added_to_temp_shelf()')
        self.assertTrue(True)
        import sim
        reload(sim)
        sim.configure('configs/config-%s-inf-2-6-10-10-10-15-orders.py' % self.concurrency)
        sim.cfg['orders_literal'] = [gen_unique_order(temp=t) for t in sim.SINGLE_TEMPS]
        sim.cfg['courier_dispatch_enabled'] = False
        sim.run()
        for o in sim.cfg['orders_literal']:
            #log('order: %s' % str(o))
            oid = o['id']
            self.assertTrue(oid in sim.kt.order_ready) # its ready for pickup and has a timestamp
            self.assertTrue(oid in sim.kt.order_locs)  # we know it's location (what shelf, or capdrop or wasted)
            loc = sim.kt.order_locs[oid]
            #log('loc: %s' % loc)
            self.assertTrue(loc in sim.kt.shelf_names) # its location is a shelf (single temp or overflow)
            self.assertEqual(loc, o['temp'])           # its the ideal shelf for its temp
            self.assertTrue(o in sim.kt.shelves[loc])  # its on the shelf the sim said
            ov = sim.kt.order_value(o, sim.kt.now)
            #log('oval: %f' % ov)
            if self.concurrency == 'T':
                self.assertRange(ov, 0.998, 1.0)   # cuz in temporal mode has been observed after sim end as low as 0.9988274574279785
            else: # priority
                self.assertEqual(ov, 1.0)          # order value is max/ideal, since fresh cuz no time passed since ready

    def test_D_shelf_capacity_and_overflow(self):
        log(type(self).__name__ + '.test_D_shelf_capacity_and_overflow()')
        import sim
        reload(sim)

        def gen_orders(temp, qty):
            return [gen_unique_order(shelf_life=100, decay_rate=0, temp=temp) for i in range(qty)]

        # because 10-10-10-15:
        should_ideal         = gen_orders('hot',    10)
        should_ideal.extend(   gen_orders('cold',   10))
        should_ideal.extend(   gen_orders('frozen', 10))
        should_overflow      = gen_orders('hot',     5)
        should_overflow.extend(gen_orders('cold',    5))
        should_overflow.extend(gen_orders('frozen',  5))

        os = list(should_ideal)
        os.extend(should_overflow)

        sim.configure('configs/config-%s-2-2-6-10-10-10-15-orders.py' % self.concurrency)
        sim.cfg['orders_literal']  = os
        #for o in sim.cfg['orders_literal']: log(o)
        sim.cfg['courier_dispatch_enabled'] = False
        sim.run()

        # do all the shelves have the capacity we expect?
        self.assertEqual(sim.cfg['shelf_capacity']['hot'],      10)
        self.assertEqual(sim.cfg['shelf_capacity']['cold'],     10)
        self.assertEqual(sim.cfg['shelf_capacity']['frozen'],   10)
        self.assertEqual(sim.cfg['shelf_capacity']['overflow'], 15)

        # is every shelf full?
        for sn in sim.kt.shelf_names:
            #log('shelf capacity reached for shelf?: %s' % sn)
            self.assertEqual(len(sim.kt.shelves[sn]), sim.cfg['shelf_capacity'][sn])

        # check that every order we think should be on the overflow shelf is actually there:
        for o in should_overflow:
            #log('order: %s' % str(o))
            oid = o['id']
            self.assertTrue(oid in sim.kt.order_ready) # its ready for pickup and has a timestamp
            self.assertTrue(oid in sim.kt.order_locs)  # we know it's location (what shelf, or capdrop or wasted)
            loc = sim.kt.order_locs[oid]
            #log('loc: %s' % loc)
            self.assertTrue(loc in sim.kt.shelf_names) # its location is a shelf (single temp or overflow)
            self.assertEqual(loc, 'overflow')          # its reported location is overflow
            self.assertTrue(o in sim.kt.shelves[loc])  # its on the shelf the sim said

    def test_E_capacity_drops(self):
        log(type(self).__name__ + '.test_E_capacity_drops()')
        import sim
        reload(sim)

        configmod = 'configs/config-%s-2-2-6-1-1-0-0-orders.py' % self.concurrency
        os =      [gen_unique_order(shelf_life=100, decay_rate=0, temp='hot')  for i in range(2)]
        os.extend([gen_unique_order(shelf_life=100, decay_rate=0, temp='cold') for i in range(2)])
        os.append( gen_unique_order(shelf_life=100, decay_rate=0, temp='frozen'))
        # we have 1 more hot order than will fit on the kitchen's hot shelf. likewise for cold.
        # no frozen capacity at all. and NO overflow capacity
        # therefore, we'd expect that the sim will capdrop the 2nd hot order, 2nd cold, and the sole frozen order:
        should_drop = (os[1], os[3], os[4]) # the 3 of the 5 orders we expect to see in the capdrop state

        sim.configure(configmod)
        sim.cfg['orders_literal'] = os
        sim.cfg['courier_dispatch_enabled'] = False
        sim.run()

        self.assertEqual(len(sim.kt.capacity_dropped), 3) # we expect to see a total of 3 capdropped orders

        for o in should_drop:
            #log('capdrop eval: %s' % str(o))
            oid = o['id']
            self.assertTrue(oid in sim.kt.order_ready)
            self.assertTrue(oid in sim.kt.order_locs)
            loc = sim.kt.order_locs[oid]
            self.assertEqual(loc, 'capdrop')
            self.assertTrue(o in sim.kt.capacity_dropped)

    def test_F_order_values(self):
        log(type(self).__name__ + '.test_F_order_values()')
        import sim
        reload(sim)

        # test order valuation's core equation

        # (order_age, shelf_life, decay_rate, shelf_decay_modifier), order_value
        self.assertEqual(sim.order_value(0,     100,50,1), 1.0) # no age, so max value
        self.assertEqual(sim.order_value(1,     100,50,1), 0.5) # half life, so half value
        self.assertEqual(sim.order_value(2,     100,50,1), 0.0) # shelf time reaches limit, reaches 0 value
        self.assertLess( sim.order_value(2.0001,100,50,1), 0.0) # shelf time past limit, negative value
        self.assertEqual(sim.order_value(0,     100,50,2), 1.0) # these next 4 are like above except decays 2x as fast
        self.assertEqual(sim.order_value(0.5,   100,50,2), 0.5)
        self.assertEqual(sim.order_value(1,     100,50,2), 0.0)
        self.assertLess( sim.order_value(1.0001,100,50,2), 0.0)

       # test order valuation's higher-level algorithm, where an order has been prepared and waiting on a shelf for pickup

        now = time() # just need a time-ish float
        perm = '%s-2-2-6-10-10-10-15-orders' % self.concurrency
        configmod = 'configs/config-%s.py' % perm
        sim.configure(configmod)
        sim.kt = sim.KitchenThread(now)
        for t in sim.SINGLE_TEMPS:
            for shelf in (t,'overflow'):
                order = gen_unique_order()
                order['temp'] = t
                order['shelfLife'] = 100
                order['decayRate'] = 50 
                sim.kt.order_ready[order['id']] = now
                sim.kt.add_order_to_shelf(order,shelf)
                if shelf == t: # order is on its ideal temp shelf
                    self.assertEqual(sim.kt.order_value(order,now),        1.0)
                    self.assertEqual(sim.kt.order_value(order,now+1),      0.5)
                    self.assertEqual(sim.kt.order_value(order,now+2),      0.0)
                    self.assertLess( sim.kt.order_value(order,now+2.0001), 0.0)
                else: # order is on the overflow shelf
                    self.assertEqual(sim.kt.order_value(order,now),        1.0)
                    self.assertEqual(sim.kt.order_value(order,now+0.5),    0.5)
                    self.assertEqual(sim.kt.order_value(order,now+1),      0.0)
                    self.assertLess( sim.kt.order_value(order,now+1.0001), 0.0)

    def test_G_waste(self):
        log(type(self).__name__ + '.test_G_waste()')
        import sim
        reload(sim)

        os = [gen_unique_order(shelf_life=100, decay_rate=0),   # will never waste away. will be delivered
              gen_unique_order(shelf_life=100, decay_rate=300), # discovered as waste prior to its courier arriving
              gen_unique_order(shelf_life=100, decay_rate=300), # discovered as waste prior to its courier arriving
              gen_unique_order(shelf_life=100, decay_rate=300)] # discovered as waste by its courier upon arrival
        # only the last 3 of the 4 should waste away
        should_deliver = (os[0],)
        should_waste = (os[1], os[2], os[3])

        configmod = 'configs/config-%s-0.5-3-3-10-10-10-15-orders.py' % self.concurrency
        sim.configure(configmod)
        sim.cfg['orders_literal'] = os
        sim.run()

        self.assertEqual(sim.kt.counts['event:order_received'], len(os)) # 4

        for o in os:
            ov = sim.kt.order_value(o, sim.kt.now)
            log('o: %s, %f' % (str(o), ov))

        for o in should_waste:
            ov = sim.kt.order_value(o, sim.kt.now)
            log('sw: %s, %f' % (str(o), ov))
            self.assertTrue(o in sim.kt.wasted)

        for o in sim.kt.wasted:
            ov = sim.kt.order_value(o, sim.kt.now)
            log('w: %s, %s' % (str(o), str(ov)))
            self.assertTrue(o in should_waste)
            oid = o['id']
            self.assertEqual(sim.kt.order_locs[oid], 'wasted')

        self.assertEqual(len(sim.kt.wasted),                       len(should_waste)) # 3
        self.assertEqual(sim.kt.counts['ordercheck_wasted'],       2)
        self.assertEqual(sim.kt.counts['pickupfail_wasted_prior'], 2)
        self.assertEqual(sim.kt.counts['pickupfail_wasted_now'],   1)

        for i in range(len(should_waste)): # check if they wasted in the order we expected
            self.assertEqual(should_waste[i], sim.kt.wasted[i])

        self.assertEqual(sim.kt.counts['orders_delivered'], len(should_deliver)) # 1

    def test_H_courier_arrival(self):
        log(type(self).__name__ + '.test_H_courier_arrival()')
        perms = ('2-2-6-10-10-10-15-orders',
                 '2-2-2-10-10-10-15-orders',
                 '2-0-0-10-10-10-15-orders',
                 'inf-2-6-10-10-10-15-orders')
        log('will be %i perms: %s' % (len(perms), perms))
        for pi,p in enumerate(perms,1):
            configmod = 'configs/config-%s-%s.py' % (self.concurrency, p)
            log('  perm %i of %i: %s' % (pi,len(perms),configmod))
            import sim
            reload(sim)
            sim.configure(configmod)
            orders = [gen_unique_order(shelf_life=100, decay_rate=0) for i in range(10)]
            sim.cfg['orders_literal'] = orders
            sim.run()
            for oi,o in enumerate(orders,1):
                oid = o['id']
                log('    testing order %i of %i: %s' % (oi,len(orders),oid))
                self.assertTrue(oid in sim.kt.order_ready)
                self.assertTrue(oid in sim.kt.courier_arrivals)
                r = sim.kt.order_ready[oid]
                a = sim.kt.courier_arrivals[oid]
                self.assertGreaterEqual(a,  r + sim.cfg['courier_arrival_min'])
                if self.concurrency != 'T':
                    self.assertLessEqual(a, r + sim.cfg['courier_arrival_max'])

    def test_I_large_order_counts(self):
        # This is not meant to be an exhaustive test of every code path, corner case or scaling imperfection.
        # Rather just a simple test to see if we can push a large number of typical orders through the sim,
        # under happy path conditions, in a single process lifetime, without it failing or hitting unexpected limits.
        # We also wanted to see how the real time span scaled up when ran in priority mode.
        # Also, the way the sim currently handles orders is not ideal because records of their handling accumulate in memory over time,
        # without bound. Because it was simpler to design it that way. A proper production-ready service process
        # would have bounded memory use, and might talk to a database or durable queue.
        # Note that we've specified the config and order params such that all orders should deliver successfully.
        log(type(self).__name__ + '.test_I_large_order_counts()')
        perm = '%s-2-2-2-10-10-10-15-orders' % self.concurrency # min=max to minimize randomness
        configmod = 'configs/config-%s.py' % perm
        temp = 'cold'
        def do_large_order_counts_run(total):
            log('do_large_order_counts_run(): %i orders' % total)
            import sim
            reload(sim)
            sim.configure(configmod)
            sim.cfg['orders_literal'] = [gen_unique_order(100,25,temp) for i in range(total)] 
            sim.cfg['log_config_large_orders_literal'] = False # don't spam the log with a huge dump of orders_literal cfg
            sim.run()
            self.assertEqual(sim.kt.peaks['overflow'], 0)
            if self.concurrency == 'T':
                self.assertRange(sim.kt.peaks[temp], 4, 5) #TODO
            else: # priority
                self.assertEqual(sim.kt.peaks[temp], 4)
            self.assertEqual(sim.kt.counts['orders_delivered'], len(sim.cfg['orders_literal']))
        #TODO in the following run, every once in a while, during tests, in temporal mode only, when host OS/CPU burps, you can see an abnormally large time gap in OT iterations. which then cause the final orders delivered count assert to fail, because there are pfailwaps which do not occur otherwise. Note this issue never happens in priority mode
        do_large_order_counts_run(500)  # arbitrary baseline for the 10x and 100x perms below
        if self.concurrency != 'T': # because temporal run would take too long and give negligible value
            # if P then priority-simulated time, so runs as fast as possible
            do_large_order_counts_run(5000) # orders are 10x  baseline, real time span grows by factor of  ~10.146
            do_large_order_counts_run(50000)# orders are 100x baseline, real time span grows by factor of ~112.384
        # If you want to capture a log file of this test but your disk space is low then a shortcut is to
        # comment out the 50k and 5k order runs above. The 50k run generates 135mb in logs. And the 5k run adds 13mb.
        # They are the high outliers in size. Most of the canned test permutations cause 200 to 700kb per main run log.


class C_TestBasicTemporal(B_TestBasic):
    concurrency = 'T' # temporal


def log(message, *args, **kwargs):
    #print(message, *args, **kwargs)
    logging.log(logging.DEBUG, "            :  %s" % message, *args, **kwargs)

if __name__ == '__main__':
    logging.basicConfig(stream=sys.stdout, format='%(levelname)-5s %(threadName)s: %(message)s', level=logging.DEBUG)
    current_thread().setName('MT')
    log('test.py sys.argv: %s' % sys.argv)
    main()
