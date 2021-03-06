from __future__ import print_function
from six import string_types

import numpy as np
import pickle
import time

from imgProcessor.imgIO import imread
from imgProcessor.camera.LensDistortion import LensDistortion
from imgProcessor.features.SingleTimeEffectDetection import SingleTimeEffectDetection
from imgProcessor.camera import NoiseLevelFunction
from imgProcessor.filters.medianThreshold import medianThreshold
from imgProcessor.imgSignal import signalStd


DATE_FORMAT = "%d %b %y - %H:%M"  # e.g.: '30. Nov 15 - 13:20'


def _toDate(date):
    if date is None:
        return time.localtime()
    else:
        return time.strptime(date, DATE_FORMAT)

# def newest(dates):
#     return np.argmax([time.mktime(t) for t in dates])


def _insertDateIndex(date, l):
    '''
    returns the index to insert the given date in a list
    where each items first value is a date
    '''
    return next((i for i, n in enumerate(l) if n[0] < date), len(l))


def _getFromDate(l, date):
    '''
    returns the index of given or best fitting date
    '''
    try:
        date = _toDate(date)
        i = _insertDateIndex(date, l) - 1
        if i == -1:
            return l[0]
        return l[i]
    except (ValueError, TypeError):
        # ValueError: date invalid / TypeError: date = None
        return l[0]


class CameraCalibration(object):
    '''
    Collect a arrays and parameters needed for camera calibration (.add###)
    Load and save to hard drive (.loadFromFile, .saveToFile)
    and correct images (.correct)
    '''
    ftype = '.cal'

    def __init__(self):
        self.noise_level_function = None

        self.coeffs = {
            'name': 'no camera',
            # maximum integer value depending of the bit depth of the camera
            'depth': 16,
            # available light spectra e.g. ['light', 'IR']
            'light spectra': [],
            # [ [date, [slope, intercept], info, (error)],[...] ]
            'dark current': [],
            'flat field': {},  # {light:[[date, info, array, (error)],[...] ]
            # {light:[[ date, info, LensDistortion]         ,[...] ]
            'lens': {},
            # [ [date, info, NoiseLevelFunction]            ,[...] ]
            'noise': [],
            'psf': {},
            'shape': None,
            # factor sharpness/smoothness of image used for wiener
            # deconvolution
            'balance': {}
        }
        self.temp = {}

    def _getDate(self, typ, light):
        d = self.coeffs[typ]
        if type(d) is dict:
            assert light is not None, 'need light spectrum given to access [%s]' % typ
            d = d[light]
        return d

    def dates(self, typ, light=None):
        '''
        Args:
            typ: type of calibration to look for. See .coeffs.keys() for all types available
            light (Optional[str]): restrict to calibrations, done given light source

        Returns:
            list: All calibration dates available for given typ
        '''
        try:
            d = self._getDate(typ, light)
            return [self._toDateStr(c[0]) for c in d]
        except KeyError:
            return []

    def infos(self, typ, light=None, date=None):
        '''
        Args:
            typ: type of calibration to look for. See .coeffs.keys() for all types available
            date (Optional[str]): date of calibration

        Returns:
            list: all infos available for given typ
        '''
        d = self._getDate(typ, light)
        if date is None:
            return [c[1] for c in d]
        # TODO: not struct time, but time in ms since epoch
        return _getFromDate(d, date)[1]

    def overview(self):
        '''
        Returns:
            str: an overview covering all calibrations 
            infos and shapes
        '''
        c = self.coeffs
        out = 'camera name: %s' % c['name']
        out += '\nmax value: %s' % c['depth']
        out += '\nlight spectra: %s' % c['light spectra']

        out += '\ndark current:'
        for (date, info, (slope, intercept), error) in c['dark current']:
            out += '\n\t date: %s' % self._toDateStr(date)
            out += '\n\t\t info: %s; slope:%s, intercept:%s' % (
                info, slope.shape, intercept.shape)

        out += '\nflat field:'
        for light, vals in c['flat field'].items():
            out += '\n\t light: %s' % light
            for (date, info, arr, error) in vals:
                out += '\n\t\t date: %s' % self._toDateStr(date)
                out += '\n\t\t\t info: %s; array:%s' % (info, arr.shape)

        out += '\nlens:'
        for light, vals in c['lens'].items():
            out += '\n\t light: %s' % light
            for (date, info, coeffs) in vals:
                out += '\n\t\t date: %s' % self._toDateStr(date)
                out += '\n\t\t\t info: %s; coeffs:%s' % (info, coeffs)

        out += '\nnoise:'
        for (date, info, nlf_coeff, error) in c['noise']:
            out += '\n\t date: %s' % self._toDateStr(date)
            out += '\n\t\t info: %s; coeffs:%s' % (info, nlf_coeff)

        out += '\nPoint spread function:'
        for light, vals in c['psf'].items():
            out += '\n\t light: %s' % light
            for (date, info, psf) in vals:
                out += '\n\t\t date: %s' % self._toDateStr(date)
                out += '\n\t\t\t info: %s; shape:%s' % (info, psf.shape)

        return out

    @staticmethod
    def _toDateStr(date_struct):
        return time.strftime(DATE_FORMAT, date_struct)

    @staticmethod
    def currentTime():
        return time.strftime(DATE_FORMAT)

    def _registerLight(self, light_spectrum):
        if light_spectrum not in self.coeffs['light spectra']:
            self.coeffs['light spectra'].append(light_spectrum)

    def setCamera(self, camera_name, bit_depth=16):
        '''
        Args:
            camera_name (str): Name of the camera
            bit_depth (int): depth (bit) of the camera sensor
        '''
        self.coeffs['name'] = camera_name
        self.coeffs['depth'] = bit_depth

    def addDarkCurrent(self, slope, intercept=None, date=None, info='', error=None):
        '''
        Args:
            slope (np.array)
            intercept (np.array)
            error (numpy.array)
            slope (float): dPx/dExposureTime[sec]
            error (float): absolute
            date (str): "DD Mon YY" e.g. "30 Nov 16"
        '''
        date = _toDate(date)

        self._checkShape(slope)
        self._checkShape(intercept)

        d = self.coeffs['dark current']
        if intercept is None:
            data = slope
        else:
            data = (slope, intercept)
        d.insert(_insertDateIndex(date, d), [date, info, data, error])

    def addNoise(self, nlf_coeff, date=None, info='', error=None):
        '''
        Args:
            nlf_coeff (list)
            error (float): absolute
            info (str): additional information
            date (str): "DD Mon YY" e.g. "30 Nov 16"
        '''
        date = _toDate(date)
        d = self.coeffs['noise']
        d.insert(_insertDateIndex(date, d), [date, info, nlf_coeff, error])

    def addDeconvolutionBalance(self, balance, date=None, info='',
                                light_spectrum='visible'):
        self._registerLight(light_spectrum)
        date = _toDate(date)

        f = self.coeffs['balance']
        if light_spectrum not in f:
            f[light_spectrum] = []
        f[light_spectrum].insert(_insertDateIndex(date, f[light_spectrum]),
                                 [date, info, balance])

    def addPSF(self, psf, date=None, info='', light_spectrum='visible'):
        '''
        add a new point spread function
        '''
        self._registerLight(light_spectrum)
        date = _toDate(date)

        f = self.coeffs['psf']
        if light_spectrum not in f:
            f[light_spectrum] = []
        f[light_spectrum].insert(_insertDateIndex(date, f[light_spectrum]),
                                 [date, info, psf])

    def _checkShape(self, array):
        if not isinstance(array, np.ndarray):
            return
        s = self.coeffs['shape']
        if s is None:
            self.coeffs['shape'] = array.shape
        elif s[:2] != array.shape[:2]:
            raise Exception("""array shapes are different: stored(%s), given(%s)
if shapes are transposed, execute self.transpose() once """ % (s, array.shape))

    def addFlatField(self, arr, date=None, info='', error=None,
                     light_spectrum='visible'):
        '''
        light_spectrum = light, IR ...
        '''
        self._registerLight(light_spectrum)
        self._checkShape(arr)
        date = _toDate(date)
        f = self.coeffs['flat field']
        if light_spectrum not in f:
            f[light_spectrum] = []
        f[light_spectrum].insert(_insertDateIndex(date, f[light_spectrum]),
                                 [date, info, arr, error])

    def addLens(self, lens, date=None, info='', light_spectrum='visible'):
        '''
        lens -> instance of LensDistortion or saved file
        '''
        self._registerLight(light_spectrum)
        date = _toDate(date)

        if not isinstance(lens, LensDistortion):
            l = LensDistortion()
            l.readFromFile(lens)
            lens = l

        f = self.coeffs['lens']
        if light_spectrum not in f:
            f[light_spectrum] = []
        f[light_spectrum].insert(_insertDateIndex(date, f[light_spectrum]),
                                 [date, info, lens.coeffs])

    def clearOldCalibrations(self, date=None):
        '''
        if not only a specific date than remove all except of the youngest calibration
        '''
        self.coeffs['dark current'] = [self.coeffs['dark current'][-1]]
        self.coeffs['noise'] = [self.coeffs['noise'][-1]]

        for light in self.coeffs['flat field']:
            self.coeffs['flat field'][light] = [
                self.coeffs['flat field'][light][-1]]
        for light in self.coeffs['lens']:
            self.coeffs['lens'][light] = [self.coeffs['lens'][light][-1]]

    def _correctPath(self, path):
        if not path.endswith(self.ftype):
            path += self.ftype
        return path

    @staticmethod
    def loadFromFile(path):
        cal = CameraCalibration()
        path = cal._correctPath(path)
        try:
            d = pickle.load(open(path, 'rb'))
        except UnicodeDecodeError:
            # for py2 pickels, the following works:
            with open(path, 'rb') as f:
                d = pickle.load(f, encoding='latin1')
        cal.coeffs.update(d)
        return cal

    def saveToFile(self, path):
        path = self._correctPath(path)
        c = dict(self.coeffs)
        with open(path, 'wb') as outfile:
            pickle.dump(c, outfile, protocol=pickle.HIGHEST_PROTOCOL)

    def transpose(self):
        '''
        transpose all calibration arrays
        in case different array shape orders were used (x,y) vs. (y,x)
        '''
        def _t(item):
            if type(item) == list:
                for n, it in enumerate(item):
                    if type(it) == tuple:
                        it = list(it)
                        item[n] = it
                    if type(it) == list:
                        _t(it)
                    if isinstance(it, np.ndarray) and it.shape == s:
                        item[n] = it.T

        s = self.coeffs['shape']

        for item in self.coeffs.values():
            if type(item) == dict:
                for item2 in item.values():
                    _t(item2)
            else:
                _t(item)

        self.coeffs['shape'] = s[::-1]

    def correct(self, images,
                bgImages=None,
                exposure_time=None,
                light_spectrum=None,
                threshold=0.1,
                keep_size=True,
                date=None,
                deblur=False,
                denoise=False):
        '''
        exposure_time [s]

        date -> string e.g. '30. Nov 15' to get a calibration on from date
             -> {'dark current':'30. Nov 15',
                 'flat field':'15. Nov 15',
                 'lens':'14. Nov 15',
                 'noise':'01. Nov 15'}
        '''
        print('CORRECT CAMERA ...')

        if isinstance(date, string_types) or date is None:
            date = {'dark current': date,
                    'flat field': date,
                    'lens': date,
                    'noise': date,
                    'psf': date}

        if light_spectrum is None:
            try:
                light_spectrum = self.coeffs['light spectra'][0]
            except IndexError:
                pass

        # do we have multiple images?
        if (type(images) in (list, tuple) or
                (isinstance(images, np.ndarray) and
                 images.ndim == 3 and
                 images.shape[-1] not in (3, 4)  # is color
                 )):
            if len(images) > 1:

                # 0.NOISE
                n = self.coeffs['noise']
                if self.noise_level_function is None and len(n):
                    n = _getFromDate(n, date['noise'])[2]
                    self.noise_level_function = lambda x: NoiseLevelFunction.boundedFunction(
                        x, *n)

                print('... remove single-time-effects from images ')
                # 1. STE REMOVAL ONLY IF >=2 IMAGES ARE GIVEN:
                ste = SingleTimeEffectDetection(images, nStd=4,
                                                noise_level_function=self.noise_level_function)
                image = ste.noSTE

                if self.noise_level_function is None:
                    self.noise_level_function = ste.noise_level_function
            else:
                image = np.asfarray(imread(images[0], dtype=np.float))
        else:
            image = np.asfarray(imread(images, dtype=np.float))

        self._checkShape(image)

        self.last_light_spectrum = light_spectrum
        self.last_img = image

        # 2. BACKGROUND REMOVAL
        try:
            self._correctDarkCurrent(image, exposure_time, bgImages,
                                     date['dark current'])
        except Exception as errm:
            print('Error: %s' % errm)

        # 3. VIGNETTING/SENSITIVITY CORRECTION:
        try:
            self._correctVignetting(image, light_spectrum,
                                    date['flat field'])
        except Exception as errm:
            print('Error: %s' % errm)

        # 4. REPLACE DECECTIVE PX WITH MEDIAN FILTERED FALUE
        if threshold > 0:
            print('... remove artefacts')
            try:
                image = self._correctArtefacts(image, threshold)
            except Exception as errm:
                print('Error: %s' % errm)
        # 5. DEBLUR
        if deblur:
            print('... remove blur')
            try:
                image = self._correctBlur(image, light_spectrum, date['psf'])
            except Exception as errm:
                print('Error: %s' % errm)
        # 5. LENS CORRECTION:
        try:
            image = self._correctLens(image, light_spectrum, date['lens'],
                                      keep_size)
        except TypeError:
            'Error: no lens calibration found'
        except Exception as errm:
            print('Error: %s' % errm)
        # 6. Denoise
        if denoise:
            print('... denoise ... this might take some time')
            image = self._correctNoise(image)

        print('DONE')
        return image

    def _correctNoise(self, image):
        '''
        denoise using non-local-means
        with guessing best parameters
        '''
        from skimage.restoration import denoise_nl_means  # save startup time
        image[np.isnan(image)] = 0  # otherwise result =nan
        out = denoise_nl_means(image,
                               patch_size=7,
                               patch_distance=11,
                               #h=signalStd(image) * 0.1
                               )

        return out

    def _correctDarkCurrent(self, image, exposuretime, bgImages, date):
        '''
        open OR calculate a background image: f(t)=m*t+n
        '''
        # either exposureTime or bgImages has to be given
#         if exposuretime is not None or bgImages is not None:
        print('... remove dark current')

        if bgImages is not None:

            if (type(bgImages) in (list, tuple) or
                    (isinstance(bgImages, np.ndarray) and
                     bgImages.ndim == 3)):
                if len(bgImages) > 1:
                    # if multiple images are given: do STE removal:
                    nlf = self.noise_level_function
                    bg = SingleTimeEffectDetection(
                        bgImages, nStd=4,
                        noise_level_function=nlf).noSTE
                else:
                    bg = imread(bgImages[0])
            else:
                bg = imread(bgImages)
        else:
            bg = self.calcDarkCurrent(exposuretime, date)
        self.temp['bg'] = bg
        image -= bg

    def calcDarkCurrent(self, exposuretime, date=None):
        d = self.coeffs['dark current']
        d = _getFromDate(d, date)
        if type(d) == tuple:
            # calculate bg image:
            offs, ascent = d[2]
            bg = offs + ascent * exposuretime
            mx = 2**self.coeffs['depth'] - 1  # maximum value
            with np.errstate(invalid='ignore'):
                bg[bg > mx] = mx
        else:
            # only constant bg value of array given
            bg = d[2]

        return bg

    def _correctVignetting(self, image, light_spectrum, date):
        d = self.getCoeff('flat field', light_spectrum, date)
        if d is not None:
            print('... remove vignetting and sensitivity')
            d = d[2]
            i = d != 0
            image[i] /= d[i]
#         with np.errstate(divide='ignore'):
#             out = image / d
#         #set
#         out[i]=image[i]
        # return image

    def _correctBlur(self, image, light_spectrum, date):
        # save startup time
        from skimage.restoration.deconvolution import unsupervised_wiener, wiener

        d = self.getCoeff('psf', light_spectrum, date)
        if not d:
            print('skip deconvolution // no PSF set')
            return image
        psf = d[2]
        mx = image.max()
        image /= mx

        balance = self.getCoeff('balance', light_spectrum, date)
        if balance is None:
            print(
                'no balance value for wiener deconvolution found // use unsupervised_wiener instead // this will take some time')
            deconvolved, _ = unsupervised_wiener(image, psf)
        else:
            deconvolved = wiener(image, psf, balance[2])
        deconvolved[deconvolved < 0] = 0
        deconvolved *= mx
        return deconvolved

    def _correctArtefacts(self, image, threshold):
        '''
        Apply a thresholded median replacing high gradients 
        and values beyond the boundaries
        '''
        image = np.nan_to_num(image)
        medianThreshold(image, threshold, copy=False)
        return image

    def getLens(self, light_spectrum, date):
        d = self.getCoeff('lens', light_spectrum, date)
        if d:
            return LensDistortion(d[2])

    def _correctLens(self, image, light_spectrum, date, keep_size):
        lens = self.getLens(light_spectrum, date)
        if lens:
            print('... correct lens distortion')
            return lens.correct(image, keepSize=keep_size)
        return image

    def deleteCoeff(self, name, date, light=None):
        try:
            c = self.coeffs[name][light]
        except TypeError:
            # not light dependent
            c = self.coeffs[name]
        d = _toDate(date)
        i = _insertDateIndex(d, c) - 1
        if i != -1:
            c.pop(i)
        else:
            raise Exception('no coeff %s for date %s' % (name, date))

    def getCoeff(self, name, light=None, date=None):
        '''
        try to get calibration for right light source, but
        use another if they is none existent
        '''
        d = self.coeffs[name]

        try:
            c = d[light]
        except KeyError:
            try:
                k, i = next(iter(d.items()))
                if light is not None:
                    print(
                        'no calibration found for [%s] - using [%s] instead' % (light, k))
            except StopIteration:
                return None
            c = i
        except TypeError:
            # coeff not dependent on light source
            c = d
        return _getFromDate(c, date)

    def uncertainty(self, img=None, light_spectrum=None):
        # TODO: review
        if img is None:
            img = self.last_img
        if light_spectrum is None:
            light_spectrum = self.last_light_spectrum

        s = img.shape
        position = self.coeffs['lenses'][
            light_spectrum].getUncertainty(s[1], s[0])

        intensity = (
            self.coeffs['dark_RMSE']**2 +
                    (self.coeffs['vignetting_relUncert'][light_spectrum] * img)**2 +
            self.coeffs['sensitivity_RMSE']**2
        )**0.5
        # make relative:
        img = img.copy()
        img[img == 0] = 1
        intensity /= img
        # apply lens distortuion:
        intensity = self.coeffs['lenses'][light_spectrum].correct(
            intensity, keepSize=True)
        return intensity, position


if __name__ == '__main__':
    # TODO: generate synthetic distortion img and calibration
    pass
#
