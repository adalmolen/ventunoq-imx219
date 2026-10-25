import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / 'runtime'
spec = importlib.util.spec_from_file_location('native_look', ROOT / 'picture_look.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def reference(image, look):
    source = np.asarray(image).astype(np.int32)
    strength = round(look.profile['noise_strength'] * 256)
    if strength:
        padded = np.pad(source, ((1,1),(1,1),(0,0)), mode='edge')
        smoothed = (source * 4 + padded[:-2,1:-1] + padded[2:,1:-1] +
                    padded[1:-1,:-2] + padded[1:-1,2:] + 4) >> 3
        source = (strength * smoothed + (256-strength) * source + 128) >> 8
    table = np.asarray(list(look.curves)).reshape(3,256)
    mapped = np.stack([table[c,source[:,:,c]] for c in range(3)],axis=2).astype(np.int32)
    y = (77*mapped[:,:,0] + 150*mapped[:,:,1] + 29*mapped[:,:,2] + 128) >> 8
    q = round(look.profile['saturation'] * 256)
    return np.clip((q*mapped + (256-q)*y[:,:,None] + 128) >> 8,0,255).astype(np.uint8)


class NativeTests(unittest.TestCase):
    def test_exact_reference_boundaries_noise_saturation_and_threads(self):
        rng=np.random.default_rng(78)
        for height,width in [(1,1),(1,33),(33,1),(2,2),(7,9),(31,32),(33,127),(1080,1920)]:
            image=Image.fromarray(rng.integers(0,256,(height,width,3),dtype=np.uint8))
            for strength in (0,.5,1):
                for threads in (1,2):
                    profile=dict(native.DEFAULT,noise_strength=strength,threads=threads)
                    if width < 100: profile['saturation']=1.8
                    look=native.Look(profile)
                    with self.subTest(shape=(height,width),strength=strength,threads=threads):
                        np.testing.assert_array_equal(np.asarray(look.apply(image)),reference(image,look))
                        np.testing.assert_array_equal(np.asarray(look.apply_array(np.asarray(image))),reference(image,look))

    def test_neutral_endpoints_and_monotonic_tones(self):
        image=Image.fromarray(np.broadcast_to(np.arange(256,dtype=np.uint8)[None,:,None],(2,256,3)).copy())
        look=native.Look(dict(native.DEFAULT,noise_strength=0,red_tint=1,blue_tint=1))
        out=np.asarray(look.apply(image))
        self.assertTrue(np.all(out[:,0]==0));self.assertTrue(np.all(out[:,-1]==255))
        self.assertTrue(np.all(np.diff(out[0,:,0].astype(int))>=0))
        self.assertTrue(np.all(out[:,:,0]==out[:,:,1]));self.assertTrue(np.all(out[:,:,1]==out[:,:,2]))

    def test_v1_profile_compatible_during_update(self):
        old={'schema':1,'exposure_lines':1600,'linear_brightness':4.,'saturation':1.35,'red_tint':1.04,'blue_tint':.96}
        look=native.Look(old)
        self.assertEqual(look.profile['schema'],3)
        self.assertEqual(look.profile['noise_strength'],0)

    def test_noise_reduced_on_flat_patch(self):
        rng=np.random.default_rng(23)
        image=Image.fromarray(np.clip(45+rng.normal(0,3,(200,200,3)),0,255).astype(np.uint8))
        filtered=np.asarray(native.Look(native.DEFAULT).apply(image)).astype(float)
        unfiltered=np.asarray(native.Look(dict(native.DEFAULT,noise_strength=0)).apply(image)).astype(float)
        self.assertLess((filtered[:,:,0]-filtered[:,:,1]).std(),(unfiltered[:,:,0]-unfiltered[:,:,1]).std()*.7)

    def test_bad_profiles_rejected(self):
        for key,value in [('threads',3),('threads',1.5),('noise_strength',-1),('schema',True),('exposure_lines',1600.5)]:
            with self.subTest(key=key),self.assertRaises(ValueError):native.validate(dict(native.DEFAULT,**{key:value}))


if __name__=='__main__':unittest.main()
