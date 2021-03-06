from __future__ import division

from numba import jit
import numpy as np



def interpolate2dStructuredIDW(grid, mask, kernel=15, power=2, fx=1, fy=1):
    '''
    replace all values in [grid] indicated by [mask]
    with the inverse distance weighted interpolation of all values within 
    px+-kernel
    [power] -> distance weighting factor: 1/distance**[power]

    '''
    weights = np.empty(shape=((2*kernel+1,2*kernel+1)))
    for xi in range(-kernel,kernel+1):
        for yi in range(-kernel,kernel+1):
            dist = ((fx*xi)**2+(fy*yi)**2)
            if dist:
                weights[xi+kernel,yi+kernel] = 1 / dist**(0.5*power)

    return _calc(grid, mask, kernel, weights)
    
    
@jit(nopython=True)
def _calc(grid, mask, kernel, weights):
    gx = grid.shape[0]
    gy = grid.shape[1]
    
    #FOR EVERY PIXEL
    for i in range(gx):
        for j in range(gy):
            
            if mask[i,j]:
                
                xmn = i-kernel
                if xmn < 0:
                    xmn = 0
                xmx = i+kernel
                if xmx > gx:
                    xmx = gx
                    
                ymn = j-kernel
                if ymn < 0:
                    ymn = 0
                ymx = j+kernel
                if ymx > gy:
                    ymx = gy
                    
                sumWi = 0.0
                value = 0.0 
                c = 0
                #FOR EVERY NEIGHBOUR IN KERNEL              
                for xi in range(xmn,xmx+1):
                    for yi in range(ymn,ymx+1):
                        if  (xi != i or yi != j) and not mask[xi,yi]:
                            wi = weights[xi-i+kernel,yi-j+kernel]
                            sumWi += wi
                            value += wi * grid[xi,yi] 
                        c += 1 
                if sumWi:
                    grid[i,j] = value / sumWi               

    return grid



if __name__ == '__main__':
    import pylab as plt
    import sys
    from time import time

    shape = (200,200)

    #array with random values:
    arr = np.random.rand(*shape)
    #mask containing valid cells: 
    mask = np.random.randint(50, size=shape)
    mask[mask<1]=False
    mask = mask.astype(bool)

    #substituting all cells with mask==True with interpolated value:
    t0 = time()
    arr1 = interpolate2dStructuredIDW(arr.copy(), mask, kernel=20,power=1)
    arr2 = interpolate2dStructuredIDW(arr.copy(), mask, kernel=20,power=2)
    arr3 = interpolate2dStructuredIDW(arr.copy(), mask, kernel=20,power=3)
    arr5 = interpolate2dStructuredIDW(arr.copy(), mask, kernel=20,power=5)
    print ('time=%f' %(time()-t0))

    
    
    if 'no_window' not in sys.argv:
        plt.figure('power=1')
        arr1[~mask] = np.nan
        plt.imshow(arr1)
        
        plt.figure('power=2')
        arr2[~mask] = np.nan
        
        plt.imshow(arr2)        
        plt.figure('power=3')
        arr3[~mask] = np.nan
        plt.imshow(arr3) 
               
        plt.figure('power=5')
        arr5[~mask] = np.nan
        plt.imshow(arr5)
        
        plt.show()
    