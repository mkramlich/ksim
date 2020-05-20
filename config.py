{
'concurrency'                    : 'priority',    # temporal or priority
'order_rate'                     : 2.0,           # float, new orders submitted per second. may be 0 or float('inf')
'courier_arrival_min'            : 2.0,           # float, min seconds before courier arrives, in random range
'courier_arrival_max'            : 6.0,           # float, max, ditto above
'shelf_capacity'                 : {              # int, every capacity may be 0 or float('inf')
    'hot'                        : 10,
    'cold'                       : 10,
    'frozen'                     : 10,
    'overflow'                   : 15},
'orders_file'                    : 'orders.json', # file to read orders from
'orders_literal'                 : None,          # can be literal [] of orders; if defined they supersede the orders_file
'courier_dispatch_enabled'       : True,          # toggled off for testing only
'log_config_large_orders_literal': True           # if run with a huge orders_literal (like for a test) might want to turn this off
}
