#!/usr/bin/env python
# coding: utf-8


import scipy.io
import glob
import numpy as np
import keras
import scipy.stats
import vincenty
import sys

def load_val_data(fold):
    l = range(10)
    trnIdx = [fold]
    trn = []
    for ii in trnIdx:
        foldData = np.load('ecr_data2_'+str(ii)+'.npy', allow_pickle=True)[()]
        for subjData in foldData:
            for ttData in foldData[subjData]:
                [org,data] = foldData[subjData][ttData]
                trn.append(org)
    return trn

class baselines:
    def __init__(self,orgEEG,system='10-20_system'):
        
        ignoreCh = set(['EEGA2A1','EDFAnnotations','ECGECG']);
        
        self.sysMap = scipy.io.loadmat('./baselines/maps/'+system+'.mat')
        mapChan = list(set([ channel[0] for channel in self.sysMap['map'].flatten().tolist()]))
        self.eegChan = [orgEEG['chanlocs'][0][0,ii][0][0].replace(' ','').replace('-','') for ii in range(np.size(orgEEG['chanlocs'][0]))]
        distLabels = [x[0] for x in list(orgEEG['chanlocs'][0].dtype.fields.items())]
        xIdx = distLabels.index('X')
        yIdx = distLabels.index('Y')
        zIdx = distLabels.index('Z')
        thtIdx = distLabels.index('sph_theta')
        phiIdx = distLabels.index('sph_phi')
        self.distances = {}
        for ii,chan in enumerate(self.eegChan):
            if chan in ignoreCh:
                continue
            self.distances[chan] = {}
            self.distances[chan]['x'] = float(orgEEG['chanlocs'][0][0,ii][xIdx])
            self.distances[chan]['y'] = float(orgEEG['chanlocs'][0][0,ii][yIdx])
            self.distances[chan]['z'] = float(orgEEG['chanlocs'][0][0,ii][zIdx])
            self.distances[chan]['tht'] = np.radians(float(orgEEG['chanlocs'][0][0,ii][thtIdx]))
            self.distances[chan]['phi'] = np.radians(float(orgEEG['chanlocs'][0][0,ii][phiIdx]))
        return
        
    def broadcast_to_8x8(self,A):
        B = np.hstack((A[:,:2,:],np.tile(A[:,2,:].reshape(5,1,10),(1,2,1)),A[:,3:,:]))
        C = np.vstack((B[:2,:,:],np.tile(B[2,:,:].reshape(1,6,10),(2,1,1)),B[3:,:,:]))
        D = A[0,0,:].reshape((1,1,10)) #A1-A2 ear channel
        E = A[4,4,:].reshape((1,1,10)) #A1-A2 ear channel
        F = np.array(np.vstack((np.hstack((D,E)),np.hstack((E,D)))))
        G = np.tile(F,(4,4,1))
        G[1:7,1:7,:] = C
        return G[:,:,:8]
        
    def normalize_data(self,orgEEG,startIdx,endIdx):
        EEG5x5 = []
        EEG8x8 = []
        full_data = orgEEG['data'][0]
        for epoch in range(startIdx,endIdx):
            EEG5x5.append(np.zeros((5,5,10)))
            for ii in range(orgEEG['data'][0].shape[0]):
                chan_name = orgEEG['chanlocs'][0][0][ii][0][0].replace(" ","").replace("-","")
                xy_tulip = np.where(self.sysMap['map']==chan_name)
                for jj in range(np.size(xy_tulip[0])):
                    x = xy_tulip[0][jj]
                    y = xy_tulip[1][jj]
                    EEG5x5[-1][x,y,:] = full_data[ii,8*epoch:8*(epoch+1)+2]
            EEG5x5[-1] = scipy.stats.zscore(EEG5x5[-1],2)
            EEG8x8.append(self.broadcast_to_8x8(EEG5x5[-1]))
        return EEG8x8
                
    def EUD(self,EEG,p=1):
        mse = []
        for intChan in  self.distances.keys():
            [ii],[jj]=np.where(self.sysMap['map'] == [intChan])
            orgChan = EEG[ii,jj,:].reshape(np.shape(EEG)[2])
            newChan = np.zeros(np.shape(EEG)[2])
            normChan = 0
            for chan in self.distances.keys():
                dij = 0
                if chan == intChan:
                    continue
                dij += (self.distances[chan]['x']-self.distances[intChan]['x'])**2
                dij += (self.distances[chan]['y']-self.distances[intChan]['y'])**2
                dij += (self.distances[chan]['z']-self.distances[intChan]['z'])**2
                dij = np.sqrt(dij)
                [ii],[jj]=np.where(self.sysMap['map'] == [chan])
                newChan += EEG[ii,jj,:].reshape(np.shape(EEG)[2]) / (dij**p)
                normChan += 1/(dij**p)
            newChan = newChan / normChan
            orgChan = scipy.stats.zscore(orgChan)
            newChan = scipy.stats.zscore(newChan)
            mse.append(float(keras.losses.mean_squared_error(orgChan,newChan)))
        return mse
    
    def GCD(self,EEG):
        mse = []
        for intChan in  self.distances.keys():
            [ii],[jj]=np.where(self.sysMap['map'] == [intChan])
            orgChan = EEG[ii,jj,:].reshape(np.shape(EEG)[2])
            newChan = np.zeros(np.shape(EEG)[2])
            for chan in self.distances.keys():
                dij = 0
                if chan == intChan:
                    continue
                dij += np.sin((self.distances[intChan]['phi']-self.distances[chan]['phi'])/2)**2
                dij += np.cos(self.distances[intChan]['phi'])*self.distances[chan]['phi']*np.sin((self.distances[intChan]['tht']-self.distances[chan]['tht'])/2)**2
                #print(dij)
                dij = np.sqrt(dij)
                dij = 2*np.arcsin(dij)
                [ii],[jj]=np.where(self.sysMap['map'] == [chan])
                newChan += dij*EEG[ii,jj,:].reshape(np.shape(EEG)[2])
            orgChan = scipy.stats.zscore(orgChan)
            newChan = scipy.stats.zscore(newChan)
            mse.append(float(keras.losses.mean_squared_error(orgChan,newChan)))
        return mse
    
    def EGL(self,EEG,p=1):
        mse = []
        for intChan in  self.distances.keys():
            [ii],[jj]=np.where(self.sysMap['map'] == [intChan])
            orgChan = EEG[ii,jj,:].reshape(np.shape(EEG)[2])
            newChan = np.zeros(np.shape(EEG)[2])
            normChan = 0
            for chan in self.distances.keys():
                dij = 0
                if chan == intChan:
                    continue
                dij = vincenty.vincenty((self.distances[intChan]['phi'],self.distances[intChan]['tht']),(self.distances[chan]['phi'],self.distances[chan]['tht']))
                [ii],[jj]=np.where(self.sysMap['map'] == [chan])
                newChan += EEG[ii,jj,:].reshape(np.shape(EEG)[2]) / (dij**p)
                normChan += 1/(dij**p)
            newChan = newChan / normChan
            orgChan = scipy.stats.zscore(orgChan)
            newChan = scipy.stats.zscore(newChan)
            mse.append(float(keras.losses.mean_squared_error(orgChan,newChan)))
        return mse

    def new_EUD(self,EEG,ii,jj,p=1):
        orgChan = EEG[ii,jj,:].reshape(np.shape(EEG)[2])
        newChan = np.zeros(np.shape(EEG)[2])
        intChan = self.sysMap['map'][ii,jj][0]
        normChan = 0
        for chan in self.distances.keys():
            dij = 0
            if chan == intChan:
                continue
            dij += (self.distances[chan]['x']-self.distances[intChan]['x'])**2
            dij += (self.distances[chan]['y']-self.distances[intChan]['y'])**2
            dij += (self.distances[chan]['z']-self.distances[intChan]['z'])**2
            dij = np.sqrt(dij)
            [ii],[jj]=np.where(self.sysMap['map'] == [chan])
            newChan += EEG[ii,jj,:].reshape(np.shape(EEG)[2]) / (dij**p)
            normChan += 1/(dij**p)
        newChan = newChan / normChan
        orgChan = scipy.stats.zscore(orgChan)
        newChan = scipy.stats.zscore(newChan)
        return newChan
        
    def new_EGL(self,EEG,ii,jj,p=1):
        orgChan = EEG[ii,jj,:].reshape(np.shape(EEG)[2])
        newChan = np.zeros(np.shape(EEG)[2])
        intChan = self.sysMap['map'][ii,jj][0]
        normChan = 0
        for chan in self.distances.keys():
            dij = 0
            if chan == intChan:
                continue
            dij = vincenty.vincenty((self.distances[intChan]['phi'],self.distances[intChan]['tht']),\
                           (self.distances[chan]['phi'],self.distances[chan]['tht']))
            [ii],[jj]=np.where(self.sysMap['map'] == [chan])
            newChan += EEG[ii,jj,:].reshape(np.shape(EEG)[2]) / (dij**p)
            normChan += 1/(dij**p)
        newChan = newChan / normChan
        orgChan = scipy.stats.zscore(orgChan)
        newChan = scipy.stats.zscore(newChan)
        return newChan
    
    def occlude(self,EEGList,ii,jj):
        popEEG = []
        for EEG in EEGList:
            A = EEG.copy()
            A[ii,jj,:] = np.zeros((1,1,8))
            popEEG.append(A)
        return popEEG

def calc_mse(orgEEG,intEEG):
    mse = list()
    for iChan in range(19):
        orgChanData = orgEEG[0]['data'][iChan]
        intChanData = intEEG[iChan]['data'][0,0][iChan]
        mse.append(np.array(keras.losses.mean_squared_error(orgChanData,intChanData)))
    return np.mean(mse)

if __name__ == "__main__":
    # The fold here is the data file, devide the data for easire parallelization
    fold  = int(sys.argv[1])
    p = 5 #power param between -4 and 4
    
    # This file is from the original data and simply carries meta
    # information such as channel names and locations
    files = glob.glob('./subject*_1_intrp.mat')
    
    orgEEG = scipy.io.loadmat(files[0])['EEG'][0]
    
    baseline = baselines(orgEEG)
    trn = load_val_data(fold)
    EUD_trn_res = []
    EGL_trn_res = []
    for dat in trn:
        EUD_trn_res.append(np.mean(baseline.EUD(dat,p)))
        EGL_trn_res.append(np.mean(baseline.EGL(dat,p)))
    np.save('./EUD_data'+str(fold)+'_p'+str(p),EUD_trn_res)
    np.save('./EGL_data'+str(fold)+'_p'+str(p),EGL_trn_res)
