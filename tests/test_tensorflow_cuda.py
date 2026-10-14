"""Optional hardware test for TensorFlow's CUDA execution path."""

import os

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("EXHALE_TEST_CUDA") != "1",
    reason="set EXHALE_TEST_CUDA=1 to run the CUDA hardware test",
)


def test_tensorflow_executes_on_gpu():
    """Require a visible GPU and execute a TensorFlow operation on it."""
    tf = pytest.importorskip("tensorflow")
    build_info = tf.sysconfig.get_build_info()
    assert tf.test.is_built_with_cuda(), (
        f"TensorFlow {tf.__version__} is not a CUDA build: {build_info}"
    )

    gpus = tf.config.list_physical_devices("GPU")
    assert gpus, (
        f"TensorFlow {tf.__version__} detected no GPU. Build information: {build_info}"
    )

    with tf.device("/GPU:0"):
        left = tf.constant([[1.0, 2.0], [3.0, 4.0]])
        right = tf.constant([[5.0, 6.0], [7.0, 8.0]])
        result = tf.matmul(left, right)

    assert "GPU:0" in result.device
    assert result.numpy().tolist() == [[19.0, 22.0], [43.0, 50.0]]
