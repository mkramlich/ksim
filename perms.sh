#!/bin/sh

PERMS=(
P-0-2-6-10-10-10-15-orders
P-2-0-0-10-10-10-15-orders
P-2-2-2-10-10-10-15-orders
P-2-2-6-0-0-0-0-orders
P-2-2-6-1-1-0-0-orders
P-2-2-6-10-10-10-15-orders
P-2-2-6-inf-inf-inf-0-orders
P-inf-2-6-10-10-10-15-orders
P-0.5-3-3-10-10-10-15-orders
P-0.5-300-300-10-10-10-15-orders
P-140-2-2-10-10-10-15-orders
P-140-120-120-10-10-10-15-orders
P-140-200-200-10-10-10-15-orders
P-140-200-200-inf-inf-inf-0-orders
P-140-4200-4200-10-10-10-15-orders
P-200-60-70-10-10-10-15-orders
T-0-2-6-10-10-10-15-orders
T-2-0-0-10-10-10-15-orders
T-2-2-2-10-10-10-15-orders
T-2-2-6-0-0-0-0-orders
T-2-2-6-1-1-0-0-orders
T-2-2-6-10-10-10-15-orders
T-2-2-6-inf-inf-inf-0-orders
T-inf-2-6-10-10-10-15-orders
T-0.5-3-3-10-10-10-15-orders
T-0.5-300-300-10-10-10-15-orders
T-140-2-2-10-10-10-15-orders
T-140-120-120-10-10-10-15-orders
T-140-200-200-10-10-10-15-orders
T-140-200-200-inf-inf-inf-0-orders
T-200-60-70-10-10-10-15-orders)

# NOTE there is no T/4200-4200 case above because it would take 70 mins. the other perms give enough evidence

mkdir -p logs

for P in "${PERMS[@]}"; do
    echo $P
    time ./sim.py configs/config-$P.py 2>&1 > logs/log-$P
done
