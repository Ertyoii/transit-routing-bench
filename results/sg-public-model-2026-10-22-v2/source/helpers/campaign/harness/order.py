"""Predeclared balanced randomized process orders, independent of outcomes."""
import hashlib
import json
import random


def balanced_order(cells, seed, blocks=2):
    if not cells or len({x['id'] for x in cells}) != len(cells):
        raise ValueError('nonempty unique cell IDs required')
    if blocks < 2:
        raise ValueError('at least two complete blocks required')
    rng = random.Random(seed)
    first=list(cells)
    rng.shuffle(first)
    result=[]
    for block in range(blocks):
        if block%2==0:
            if block>0:
                first=list(cells);rng.shuffle(first)
            order=list(first)
        else:
            order=list(reversed(first))
        for position,cell in enumerate(order):
            result.append({'block':block,'position':position,'cell':cell})
    commitment=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'schema':'balanced-randomized-process-order-v2','seed':seed,'blocks':blocks,'pairing':'each even random block is followed by its exact reverse; no outcome conditioning','order_sha256':commitment,'order':result}
