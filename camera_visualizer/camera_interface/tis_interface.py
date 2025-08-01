from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Type

import imagingcontrol4 as ic4
import numpy as np
import scipy

from camera_visualizer.camera_interface.mock_interface import Camera
from camera_visualizer.paths import load_data_path

ic4.Library.init()

# Camera Constants
# TIS_HEIGHT = 1200
# TIS_WIDTH = 1920
TIS_HEIGHT = 480
TIS_WIDTH = 640
TIS_MIN_EXPOSURE_MS = 15
TIS_MAX_EXPOSURE_MS = 33_333
TIS_TIMEOUT_MS = 10_000
TIS_EXPOSURE_INCREMENT = 10


# Default Camera States
TIS_DEFAULT_PIXEL_FORMAT = ic4.PixelFormat.BayerGB16
TIS_DEFAULT_EXPOSURE_TIME_MS = 500

TIS_ACCEPTED_PIXEL_FORMATS = [
    ic4.PixelFormat.Mono8,
    ic4.PixelFormat.BayerGB8,
    ic4.PixelFormat.BayerGB16,
]

# Camera Mappers
PIXEL_FORMAT_TO_BIT_DEPTH_MAP = {
    ic4.PixelFormat.Mono8: 8,
    ic4.PixelFormat.BayerGB8: 8,
    ic4.PixelFormat.BayerGB16: 16,
}

PIXEL_FORMAT_TO_SHAPE = {
    ic4.PixelFormat.Mono8: (TIS_HEIGHT, TIS_WIDTH, 1),
    ic4.PixelFormat.BayerGB8: (TIS_HEIGHT, TIS_WIDTH, 1),
    ic4.PixelFormat.BayerGB16: (TIS_HEIGHT, TIS_WIDTH, 1),
}

PIXEL_FORMAT_TO_ENVI_FORMAT = {
    ic4.PixelFormat.Mono8: 1,
    ic4.PixelFormat.BayerGB8: 1,
    ic4.PixelFormat.BayerGB16: 12,
}

def demosaic_cfa_bayer_gbrb_bilinear(bayer: np.ndarray):
    f_g = np.array([[0, 1, 0], [1, 4, 1], [0, 1, 0]], dtype=np.float32) / 8
    f_r = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], dtype=np.float32) / 16
    out = np.zeros((*bayer.shape[:2], 3))

    # Red
    out[1::2, 0::2, 0] = bayer[1::2, 0::2]
    out[..., 0] = scipy.ndimage.convolve(out[..., 0], f_r)
    # Green
    out[0::2, 0::2, 1] = bayer[0::2, 0::2]
    out[1::2, 1::2, 1] = bayer[1::2, 1::2]
    out[..., 1] = scipy.ndimage.convolve(out[..., 1], f_g)
    # Blue
    out[0::2, 1::2, 2] = bayer[0::2, 1::2]
    out[..., 2] = scipy.ndimage.convolve(out[..., 2], f_r)

    return out


@dataclass
class TisCameraState:
    save_folder: Path
    current_exposure: float = TIS_DEFAULT_EXPOSURE_TIME_MS
    timeout_ms: int = TIS_TIMEOUT_MS
    pixel_format: ic4.PixelFormat = TIS_DEFAULT_PIXEL_FORMAT
    demosaic: bool = False
    save_subfolder: str | None = None
    min_exposure: float = TIS_MIN_EXPOSURE_MS
    max_exposure: float = TIS_MAX_EXPOSURE_MS

    @property
    def save_path(self) -> Path | None:
        if self.save_subfolder is None:
            return None
        else:
            return self.save_folder / self.save_subfolder

    def shape(self) -> tuple[int, ...]:
        return PIXEL_FORMAT_TO_SHAPE[self.pixel_format]

    def bit_depth(self) -> int:
        bit_depth = PIXEL_FORMAT_TO_BIT_DEPTH_MAP[self.pixel_format]
        return bit_depth

    def dynamic_range(self) -> int:
        return 2 ** self.bit_depth() - 1


def get_envi_header(state: TisCameraState) -> dict:
    wl = [  # GB (Green-Blue) config
        [550, 450],
        [650, 550],
    ]
    wl_flat = [w for wa in wl for w in wa]
    envi_data_type = PIXEL_FORMAT_TO_ENVI_FORMAT[state.pixel_format]
    bit_depth = f"{state.bit_depth()} bits"
    return {
        'samples': TIS_WIDTH,  # width in pixels
        'lines': TIS_HEIGHT,  # height in pixels
        'bands': 1,  # raw mosaic has one band
        'interleave': 'bsq',
        'byte order': 0,  # little endian (0)
        'data type': envi_data_type,  # 1 = uint8, 12 = uint16
        'sensor type': 'The Imaging Source DFK 23UX236',

        'spatial resolution': '1920 x 1200',
        'spectral range': '450-650 nm',
        'bands count': '3 bands',
        'bit depth': bit_depth,
        # 'pixel pitch': '5.5 μm',
        # 'imager type': 'CMOS, CMOSIS CMV2000 based',
        # 'acquisition speed': 'up to 120 hyperspectral cubes/second (USB3.0 limited)',
        # 'optics': '16/25/35/50 mm lenses, F2.8, C-mount',
        'interface': 'USB3.0 + GPIO + I/O for triggering',
        # 'power consumption': '1.6 Watt',
        # 'dimensions': '26 x 26 x 31 mm',
        # 'weight': '32 g (without optics)',

        'acquisition time': datetime.now().isoformat(),
        'description': 'Bayer mosaic image snapshot.',
        'filter array size': '2x2',
        'wavelength units': 'Nanometers',
        'wavelength': wl_flat,
        'note': 'Raw mosaic. Wavelengths are listed in row-major order (left to right, top to bottom).'
    }


class TisCamera(Camera):
    grabber: ic4.Grabber
    sink: ic4.SnapSink | None
    state: TisCameraState

    def __init__(self):
        self.grabber = ic4.Grabber(dev=None)
        self.sink = None
        data_path = load_data_path()
        data_path.mkdir(parents=False, exist_ok=True)
        data_path = data_path / "tis"
        data_path.mkdir(parents=False, exist_ok=True)
        state = TisCameraState(
            save_folder=data_path,
            current_exposure=TIS_DEFAULT_EXPOSURE_TIME_MS,
            pixel_format=TIS_DEFAULT_PIXEL_FORMAT,
        )
        self.state = state

    def open(self):
        first_device_info = ic4.DeviceEnum.devices()[0]
        self.grabber.device_open(dev=first_device_info)
        self.grabber.device_property_map.set_value(
            property_name=ic4.PropId.PIXEL_FORMAT,
            value=TIS_DEFAULT_PIXEL_FORMAT,
        )
        self.grabber.device_property_map.set_value(
            property_name=ic4.PropId.WIDTH,
            value=TIS_WIDTH,
        )
        self.grabber.device_property_map.set_value(
            property_name=ic4.PropId.HEIGHT,
            value=TIS_HEIGHT,
        )
        self.grabber.device_property_map.set_value(
            property_name=ic4.PropId.EXPOSURE_TIME,
            value=self.state.current_exposure,
        )
        self.sink = ic4.SnapSink(
            accepted_pixel_formats=[
                self.state.pixel_format,
            ]
        )
        self.grabber.stream_setup(
            sink=self.sink,
            setup_option=ic4.StreamSetupOption.ACQUISITION_START,
        )

    def close(self):
        self.grabber.stream_stop()
        self.grabber.device_close()

    def shape(self) -> tuple[int, ...]:
        return self.state.shape()

    def bit_depth(self) -> int:
        return self.state.bit_depth()

    def toggle_bit_depth(self) -> None:
        pass

    def _get_frame_view(
        self,
        frame: np.ndarray,
        demosaic: bool,
    ) -> np.ndarray:
        frame_normalized = frame.astype(np.float32) / self.state.dynamic_range()
        frame_view = np.mean(frame_normalized, axis=-1)
        if demosaic:
            frame_view = demosaic_cfa_bayer_gbrb_bilinear(frame_view)
        return frame_view

    def get_frame(self, fps: float) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns a numpy frame and its view.
        """
        image_buffer = self.sink.snap_single(timeout_ms=self.state.timeout_ms)
        frame = image_buffer.numpy_wrap()
        frame_view = self._get_frame_view(
            frame=frame,
            demosaic=self.state.demosaic,
        )
        return frame, frame_view

    def get_envi_options(self) -> dict:
        return get_envi_header(state=self.state)

    def set_save_subfolder(self, subfolder: str) -> None:
        self.state.save_subfolder = subfolder
        self.state.save_path.mkdir(parents=False, exist_ok=True)

    def save_folder(self) -> Path:
        return self.state.save_path

    def exception_type(self) -> Type[Exception]:
        return ic4.IC4Exception

    def exposure(self) -> float:
        return self.state.current_exposure * 1000

    def exposure_range(self) -> tuple[int, int, int]:
        return (
            TIS_MIN_EXPOSURE_MS * 1000,
            TIS_MAX_EXPOSURE_MS * 1000,
            TIS_EXPOSURE_INCREMENT * 1000,
        )

    def set_exposure(self, exposure: int) -> bool:
        self.grabber.device_property_map.set_value(
            property_name=ic4.PropId.EXPOSURE_TIME,
            value=exposure,
        )
        self.state.current_exposure = exposure
        return True

    def _find_exposure_for_saturation(
            self,
            frame: np.ndarray,
    ) -> bool:
        """
        Binary search for exposure time to keep saturated pixels under max_saturation.
        """
        # Amount of allowed saturated pixels
        max_saturation = 100 if self.state.bit_depth() == 16 else 8000
        # Tolerated difference in number of saturated pixels
        tol = 20 if self.state.bit_depth() == 16 else 1000

        converged = False
        saturated = (frame >= self.state.dynamic_range()).sum()
        if saturated > max_saturation:
            self.state.max_exposure = self.state.current_exposure - 1
        else:
            self.state.min_exposure = self.state.current_exposure + 1
        tmp = self.state.max_exposure - self.state.min_exposure
        mid_exposure = int((self.state.max_exposure + self.state.min_exposure) // 2)

        if (
                abs(saturated - max_saturation) < tol
                or abs(tmp) < 10
                or abs(self.state.current_exposure - mid_exposure) <= 2 * TIS_EXPOSURE_INCREMENT
        ):
            converged = True
        return converged

    def init_exposure(self, max_exposure: int) -> None:
        """Initializing exposure value when launching automatic exposure search"""
        self.state.max_exposure = min(TIS_MAX_EXPOSURE_MS, int(max_exposure // 1000))
        self.state.min_exposure = TIS_MIN_EXPOSURE_MS

    def adjust_exposure(self) -> None:
        """Adjust exposure at each iteration when applying automatic exposure search"""
        self.set_exposure(
            exposure=int((self.state.max_exposure + self.state.min_exposure) // 2),
        )

    def check_exposure(self, frame: np.ndarray) -> bool:
        """Check convergence of automatic exposure"""
        return self._find_exposure_for_saturation(frame=frame)

    def toggle_view(self) -> None:
        self.state.demosaic = not self.state.demosaic


def main():
    cam = TisCamera()

    cam.open()

    # cam.grabber.device_property_map.set_value(property_name=ic4.PropId.PIXEL_FORMAT, value=ic4.PixelFormat.BayerGB16)

    frame, frame_view = cam.get_frame(fps=30)
    print(f"pixel format: {cam.sink.output_image_type.pixel_format.name}")
    print(f"frame type: {frame.dtype}, max: {frame.max()}")
    print(f"frame_view type: {frame_view.dtype}, max: {frame_view.max()}")

    cam.close()


if __name__ == "__main__":
    main()
