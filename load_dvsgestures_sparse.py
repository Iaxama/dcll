#!/bin/python
#-----------------------------------------------------------------------------
# Author: Emre Neftci
#
# Creation Date : Fri 01 Dec 2017 10:05:17 PM PST
# Last Modified : Sun 29 Jul 2018 01:39:06 PM PDT
#
# Copyright : (c) 
# Licence : GPLv2
#----------------------------------------------------------------------------- 
import struct
import numpy as np
import scipy.misc
import numpy as np
import h5py
import glob
from experimentTools import *
from dvs_timeslices import *

mapping = { 0 :'Hand Clapping'  ,
            1 :'Right Hand Wave',
            2 :'Left Hand Wave' ,
            3 :'Right Arm CW'   ,
            4 :'Right Arm CCW'  ,
            5 :'Left Arm CW'    ,
            6 :'Left Arm CCW'   ,
            7 :'Arm Roll'       ,
            8 :'Air Drums'      ,
            9 :'Air Guitar'     ,
            10:'Other'}

class SequenceGenerator(object):
    def __init__(self,
        filename = '/home/eneftci/dvs_gestures_events.hdf5',
        group = 'train',
        batch_size = 32,
        chunk_size = 500,
        ds = 2,
        size = [2, 64, 64]):

        self.ds = ds
        self.size = size
        f = h5py.File(filename, 'r')
        self.grp1 = f[group]
        self.num_classes = 11
        self.batch_size = batch_size
        self.chunk_size = chunk_size

    def reset(self):
        self.i = 0

    def next(self):
        dat,lab = next(
                self.grp1,
                batch_size = self.batch_size,
                T = self.chunk_size,
                n_classes = self.num_classes,
                size = self.size,
                ds = self.ds)
        return dat, lab

#def find_first(a, i):
#    return np.searchsorted(a,i)

def find_first(a, tgt):
    for i,aa in enumerate(a):
        if aa>tgt:
            return i
    return len(a)


    

def gather_aedat(directory, start_id, end_id, filename_prefix = 'user'):
    import glob
    fns = []
    for i in range(start_id,end_id):
        search_mask = directory+'/'+filename_prefix+"{0:02d}".format(i)+'*.aedat'
        glob_out = glob.glob(search_mask)
        if len(glob_out)>0:
            fns+=glob_out
    return fns

def aedat_to_events(filename):
    label_filename = filename[:-6] +'_labels.csv'
    labels = np.loadtxt(label_filename, skiprows=1, delimiter=',',dtype='uint32')
    events=[]
    with open(filename, 'rb') as f:
        for i in range(5):
            f.readline()
        while True: 
            data_ev_head = f.read(28)
            if len(data_ev_head)==0: break

            eventtype = struct.unpack('H', data_ev_head[0:2])[0]
            eventsource = struct.unpack('H', data_ev_head[2:4])[0]
            eventsize = struct.unpack('I', data_ev_head[4:8])[0]
            eventoffset = struct.unpack('I', data_ev_head[8:12])[0]
            eventtsoverflow = struct.unpack('I', data_ev_head[12:16])[0]
            eventcapacity = struct.unpack('I', data_ev_head[16:20])[0]
            eventnumber = struct.unpack('I', data_ev_head[20:24])[0]
            eventvalid = struct.unpack('I', data_ev_head[24:28])[0]

            if(eventtype == 1):
                event_bytes = np.frombuffer(f.read(eventnumber*eventsize), 'uint32')
                event_bytes = event_bytes.reshape(-1,2)

                x = (event_bytes[:,0] >> 17) & 0x00001FFF
                y = (event_bytes[:,0] >> 2 ) & 0x00001FFF
                p = (event_bytes[:,0] >> 1 ) & 0x00000001
                t = event_bytes[:,1]
                events.append([t,x,y,p])

            else:
                f.read(eventnumber*eventsize)
    events = np.column_stack(events)
    events = events.astype('uint32')
    clipped_events = np.zeros([4,0],'uint32')
    for l in labels:
        start = np.searchsorted(events[0,:], l[1])
        end = np.searchsorted(events[0,:], l[2])
        clipped_events = np.column_stack([clipped_events,events[:,start:end]])
    return clipped_events.T, labels

#def sort_events_bylabel(events, labels, n_classes = 11, t_cont = None):
#    if t_cont is None:
#        t_cont = np.zeros(n_classes, 'int')
#    T = events[0, -1]
#    idx = events[3,:] == pol
#    events = events[:,idx]
#    t0 = events[0, 0]
#    events[0,:] -= t0
#
#    start_idx = 0
#    end_idx = 0
#
#    labels[:,1] =(labels[:,1]-t0)//deltat
#    labels[:,2] =(labels[:,2]-t0)//deltat
#
#    sorted_events = [np.zeros([4,0]) for i in range(n_classes)]
#
#    for label, start, end in labels:
#        sorted_events[label] = np.concatenate([sorted_events[label],events[:,:,:,start:end]])    
#
#    return sorted_events

def next(hdf5_group, batch_size = 32, T = 500, n_classes = 11, ds = 2, size = [2, 64, 64]):
    batch = [None for i in range(batch_size)]
    batch_idx = np.random.randint(0,len(hdf5_group), size=batch_size)
    batch_idx_l = np.random.randint(0, n_classes, size=batch_size)
    for i, b in (enumerate(batch_idx)):
        start_time =  get_time_slice(hdf5_group[str(b)]['labels'].value, batch_idx_l[i], T)
        batch[i] = get_event_slice(hdf5_group[str(b)]['data'].value, start_time, T, ds=ds, size=size)
    return np.array(batch, dtype='float'), expand_targets(one_hot(batch_idx_l, n_classes), T).astype('float')

def get_time_slice(labels, label, T):
    start_time = labels[label][1]
    start_time = np.random.randint(start_time,labels[label][2]-T*1e3)
    return start_time

def get_event_slice(events, start_time, T, size = [128,128], ds = 1):
    idx = np.searchsorted(events[:,0], start_time)
    return chunk_evs_pol(events[idx:], deltat=1000, chunk_size=T, size = size, ds = ds)

def create_events_hdf5():
    fns_train = gather_aedat('/share/data/DvsGesture/aedat/',1,24)
    fns_test = gather_aedat('/share/data/DvsGesture/aedat/',24,30)

    with h5py.File('/share/data/DvsGesture/dvs_gestures_events.hdf5', 'w') as f:
        f.clear()

        print("processing training data...")
        key = 0
        grp = f.create_group('train')
        for file_d in fns_train:
            print(key)
            events, labels = aedat_to_events(file_d)
            subgrp = grp.create_group(str(key))
            dset_d = subgrp.create_dataset('data', events.shape, dtype=np.uint32)
            dset_d[...] = events
            dset_l = subgrp.create_dataset('labels', labels.shape, dtype=np.uint32)
            dset_l[...] = labels
            key += 1

        print("processing testing data...")
        key = 0
        grp = f.create_group('test')
        for file_d in fns_test:
            print(key)
            events, labels = aedat_to_events(file_d)
            subgrp = grp.create_group(str(key))
            dset_d = subgrp.create_dataset('data', events.shape, dtype=np.uint32)
            dset_d[...] = events
            dset_l = subgrp.create_dataset('labels', labels.shape, dtype=np.uint32)
            dset_l[...] = labels
            key += 1

def create_data(batch_size = 64 , chunk_size = 500, size = [2, 32, 32], ds = 4):
    strain = SequenceGenerator(group='train', batch_size = batch_size, chunk_size = chunk_size, size = size, ds = ds)
    stest = SequenceGenerator(group='test', batch_size = batch_size, chunk_size = chunk_size, size = size, ds = ds)
    return strain, stest

def plot_gestures_imshow(images, labels, nim=11):
    import pylab as plt
    plt.figure(figsize = [nim+2,6])
    import matplotlib.gridspec as gridspec
    gs = gridspec.GridSpec(6, nim)
    plt.subplots_adjust(left=0, bottom=0, right=1, top=0.95, wspace=.0, hspace=.04)
    categories = labels.argmax(axis=1)
    idx = 0
    for j in range(nim):
         #idx = np.where(categories==j)[0][0]
         idx += 1 
         for i in range(6):
             ax = plt.subplot(gs[i, j])
             plt.imshow(images[idx,i*50:(i*50+50),0,:,:].sum(axis=0).T)
             plt.xticks([])
             if i==0:  plt.title(mapping[labels[0,idx].argmax()], fontsize=10)
             plt.yticks([])
             plt.bone()
    return images,labels


if __name__ == "__main__":
    gen_train, gen_test = create_data(size=[2,128,128],ds=1)
    #pass





    



