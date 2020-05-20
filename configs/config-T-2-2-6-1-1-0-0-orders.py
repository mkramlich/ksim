
{
'concurrency'              : 'temporal', # temporal or priority
'order_rate'               : 2, # float, new orders submitted per second. may be 0 or float('inf')
'courier_arrival_min'      : 2, # float, min seconds before courier arrives, in random range
'courier_arrival_max'      : 6, # float, max, ditto above
'shelf_capacity'           : { # int, every capacity may be 0 or float('inf')
    'hot'                  : 1,            
    'cold'                 : 1,
    'frozen'               : 0,
    'overflow'             : 0},
'orders_file'              : 'orders.json', # file to read orders from
'orders_literal'           : None, # can be literal [] of orders; if defined they supersede the orders_file
'courier_dispatch_enabled' : True # toggled off for testing only
}