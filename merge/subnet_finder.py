import sys
import json
from collections import OrderedDict

def ip_string_to_number(ip):
  return reduce(lambda x,y: x|y, map(lambda (x,y): x << y, zip(map(int,ip.split('.')),reversed(range(0,32,8)))))

def ip_number_to_string(ip):
  return '.'.join(str((ip & (0xff << x))>>x) for x in reversed(range(0,32,8)))

def get_ip_nums_from_file(fp):
  return sorted(map(lambda x:ip_string_to_number(x.strip()),fp))

def group_sorted_ips_by_subnet(ips):
  # assume ips are sorted numbers
  found_subnets = OrderedDict()
  netmask_size = 2
  for ip in ips:
    if ip == 0 or ip == 4294967295:
      continue
    my_netmask_size = netmask_size
    my_netmask = (ip >> (my_netmask_size)) << (my_netmask_size)
    # the all-zeros and the all-ones host values are reserved for the network address of the subnet and its broadcast address
    # if we get all-zeros or all-ones, the subnet mask must be larger
    # while (ip ^ my_netmask) in (0, (1<<my_netmask_size)-1):
    while (ip == my_netmask) or ((ip+1) & my_netmask) == 0:
      my_netmask_size += 1
      my_netmask = (ip >> (my_netmask_size)) << (my_netmask_size)
    my_netmask = (my_netmask, 32 - my_netmask_size)
    ip_list = found_subnets.get(my_netmask,[])
    ip_list.append(ip)
    found_subnets[my_netmask] = ip_list
  return found_subnets

def join_subnets(subnet1, subnet2):
  if type(subnet1) == type(subnet2):
    if type(subnet1) == list:
      return list(set(subnet1+subnet2))
    else:
      out = OrderedDict()
      keys = set(subnet1.keys() + subnet2.keys())
      for k in keys:
        if k in subnet1:
          if k in subnet2:
            out[k] = join_subnets(subnet1[k],subnet2[k])
          else:
            out[k] = subnet1[k]
        else:
          out[k] = subnet2[k]
      return out
  else:
    # a list means hosts directly in this subnet, that cannot be in any other subnet (i.e. all-zeros and all-ones)
    # if we have both hosts directly here and hosts structured in subnets, it means our hypotesis of a smaller subnet is false
    # thus we flatten to a single list and consider all hosts as part of the same subnet
    if type(subnet1) == list:
      (ip_list, tree) = (subnet1, subnet2)
    else:
      (ip_list, tree) = (subnet2, subnet1)
    out = set(ip_list)
    for v in tree.values():
      out |= set(join_subnets(v,[]))
    return sorted(list(out))

def merge_subnets(found_subnets, netmask_size=2, stop_netmask_size=16):
  upper_level = OrderedDict()
  current_netmask = None
  for key, value in found_subnets.items():
    (subnet, prev_netmask_size) = key
    if netmask_size < 32 - prev_netmask_size:
      upper_level[key] = value
      continue
    elif netmask_size == 32 - prev_netmask_size:
      upper_level[key] = join_subnets(upper_level.get(key,OrderedDict()), value)
    else:
      my_netmask = (subnet >> (netmask_size)) << (netmask_size)
      my_netmask = (my_netmask, 32 - netmask_size)
      this_level = upper_level.get(my_netmask,OrderedDict())
      this_level = join_subnets(this_level,OrderedDict({key:value}))
      upper_level[my_netmask] = this_level
  if netmask_size >= stop_netmask_size:
    return upper_level
  else:
    return merge_subnets(upper_level, netmask_size+1, stop_netmask_size)

# this keeps the smallest subnet
def clean_merged(merged):
  if type(merged) == list:
    return merged
  out = OrderedDict()
  for key, value in merged.items():
    ret = clean_merged(value)
    if len(ret) > 1 or type(ret) == list:
      out[key] = ret
    else:
      (key, value) = ret.items()[0]
      out[key] = value
  return out

def represent(clean,out=None):
  if type(clean) == list:
    return list(map(ip_number_to_string, clean))
    # if len(clean) > 1:
    #   return list(map(ip_number_to_string, clean))
    # else:
    #   return ip_number_to_string(clean[0])
  elif len(clean) > 1:
    out = OrderedDict()
    for (subnet,netmask_size), value in clean.items():
      out["%s/%d" % (ip_number_to_string(subnet),netmask_size)] = represent(value)
    return out
  else:
    return represent(clean.values()[0])

def compute_cluster_likelihood(clean):
  if type(clean) == list:
    size = len(clean)
    avg = sum(map(lambda x:x/size,clean))
    std = sum(map(lambda x:(x-avg)**2,clean))**0.5
    merge = 1
    return (merge,avg,std,size)
  elif len(clean) > 1:
    avg_sum = []
    size_sum = []
    std_sum = []
    out = OrderedDict()
    for (subnet,netmask_size), value in clean.items():
      ret = compute_cluster_likelihood(value)
      (_,avg,std,size) = ret[:4]
      avg_sum.append(avg)
      std_sum.append(std)
      size_sum.append(size)
      out["%s/%d" % (ip_number_to_string(subnet),netmask_size)] = ret
    size = sum(size_sum)
    if size > 128:
      avg = sum(map(lambda (a,s): a/size*s,zip(avg_sum,size_sum)))
      std = (sum(map(lambda (d,s): (d**2)*s,zip(std_sum,size_sum)))/size)**0.5
    else:
      ip_list = join_subnets([],clean)
      (_,avg,std,size) = compute_cluster_likelihood(ip_list)

    min_val = avg - 2*std
    max_val = avg + 2*std
    common = 0

    for (a,d,s) in zip(avg_sum,std_sum,size_sum):
      minv = max(a-2*d,min_val)
      maxv = min(a+2*d,max_val)
      if minv < maxv:
        common += (maxv - minv) * s

    merge = float(common/size)/(max_val-min_val)
    v = [merge,avg,std,size,out]
    return v
  else:
    return compute_cluster_likelihood(clean.values()[0])


def traverse(tree, path):
    sub_elem_dict = tree[-1]

    res = [(tree[0], path)]
    i_val = zip(range(len(sub_elem_dict)), sub_elem_dict.values())
    for i, t in i_val:
        if type(t[-1]) == int:
            continue
        r = traverse(t, path+[i])
        res = res + r

    return res;


def flattener(t):
    res = []
    for k, v in t.iteritems():
        if type(v) == list:
            res += v
        else:
            res += flattener(v)

    return res


def pick_best_merges(stat_tree, clean_tree, num):
  all_probs = [] # tuple of (value, [index_path_down_trees])

  flattened = traverse(stat_tree, [])
  flattened = sorted(flattened, key=lambda x:x[0], reverse=True)

  to_merge = flattened[:num]
  to_merge_from_bottom = sorted(to_merge, cmp=lambda x,y:cmp(len(x[1]),len(y[1])), reverse=True)

  for v, lst in to_merge_from_bottom:
    tmp_tree = clean_tree
    for i in lst:
        tmp_tree = tmp_tree.values()[i]

    ref = clean_tree
    for i in lst[:-1]:
        ref = ref.values()[i]

    flat = flattener(tmp_tree)
    itm = ref.items()
    k, _ = itm[lst[-1]]
    ref[k] = flat

  return clean_tree

import csv
def read_tsv(fname, clean_tree):
    # read devices.log

    # for each line
    #    look inside of clean for containing subnet
    #    output line with \t possible_subnet updated

    # Read subnet.log
    # write new subnets


if __name__ == "__main__":
  ips = get_ip_nums_from_file(sys.stdin)
  groups = group_sorted_ips_by_subnet(ips)
  merged = merge_subnets(groups)
  clean = clean_merged(merged)

  s = compute_cluster_likelihood(clean)
  merged = pick_best_merges(s, clean, 8)

  print json.dumps(represent(clean))
