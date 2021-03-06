from __future__ import division

import numpy as np
from numba import njit


@njit
def interpolate2dUnstructuredIDW(x, y, v, grid, power=2):
    '''
    x,y,v --> 1d numpy.array
    grid --> 2d numpy.array

    fast if number of given values is small relative to grid resolution
    '''
    n = len(v)
    gx = grid.shape[0]
    gy = grid.shape[1]
    for i in range(gx):
        for j in range(gy):
            overPx = False  # if pixel position == point position
            sumWi = 0.0
            value = 0.0

            for k in range(n):
                xx = x[k]
                yy = y[k]
                vv = v[k]
                if xx == i and yy == j:
                    grid[i, j] = vv
                    overPx = True
                    break
                # weight from inverse distance:
                wi = 1 / ((xx - i)**2 + (yy - j)**2)**(0.5 * power)
                sumWi += wi
                value += wi * vv
            if not overPx:
                grid[i, j] = value / sumWi
    return grid


if __name__ == '__main__':
    import matplotlib.pyplot as plt
    import sys

    shape = (1000, 2000)
    nVals = 30
    # GIVING A SEED NUMBER FOR THE EXPERIENCE TO BE REPRODUCIBLE
    np.random.seed(123433789)
    grid = np.zeros(shape, dtype='float32')  # float32 gives us a lot precision

    # CREATE POINT SET
    x, y = np.random.randint(
        0, shape[0], nVals), np.random.randint(0, shape[1], nVals)
    v = np.random.randint(0, 10, nVals)  # THIS IS MY VARIABLE
    # CALCULATE
    grid = interpolate2dUnstructuredIDW(x, y, v, grid, 2)
    # PLOT
    if 'no_window' not in sys.argv:
        plt.imshow(grid.T, origin='lower', interpolation='nearest', cmap='jet')
        plt.scatter(x, y, c=v, cmap='jet', s=120)
        plt.xlim(0, grid.shape[0])
        plt.ylim(0, grid.shape[1])
        plt.grid()
        plt.show()
