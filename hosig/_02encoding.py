#内容编码：把事件内容转换为数值表示
import hashlib
import ipaddress
import re

import numpy as np
from scipy.special import ndtr

from .config import Config


def stable_hash(text, salt="", digest_size=8):
    digest = hashlib.blake2b(
        str(text).encode("utf-8"), key=salt.encode("utf-8")[:64], digest_size=digest_size,
    ).digest()
    return int.from_bytes(digest, "big")


def payload_tokens(payload):
    return re.findall(r"[\w./:@=+-]+", payload.lower())


class ContentEncoder:
    def __init__(self, config: Config):
        self.config = config
        # 创建一个随机数生成器
        generator = np.random.default_rng(config.seed)
        # 编码一条网络事件的维度
        dimension = config.vocabulary_size + 4
        # 生成一个由随机数字组成的矩阵，并保存起来，后面用它把网络安全事件的原始特征转换成统一长度的数字向量
        # 就是让这个生成器按照正态分布生成随机数字。
        # 在 ContentEncoder 中，使用 1 / np.sqrt(dimension)，
        # 是为了让随机投影矩阵中的权重随着输入维度增大而适当减小，控制多个特征相加后的数值规模。
        self.projection = generator.normal(
            0, 1 / np.sqrt(dimension), (dimension, config.embedding_dim),
        ).astype(np.float32)

    def _ip_features(self, value):
        address = ipaddress.ip_address(value)
        prefixes = (24, 16) if address.version == 4 else (64, 48)
        return [
            stable_hash(str(ipaddress.ip_network(f"{address}/{prefix}", strict=False)), digest_size=4)
            / (2**32 - 1)
            for prefix in prefixes
        ]

    def transform(self, events):
        if not events:
            return np.empty((0, self.config.embedding_dim), dtype=np.float32)
        features = np.zeros((len(events), self.config.vocabulary_size + 4), dtype=np.float32)
        for index, event in enumerate(events):
            features[index, :4] = self._ip_features(event.src_ip) + self._ip_features(event.dst_ip)
            for token in payload_tokens(event.payload):
                slot = 4 + stable_hash(token) % self.config.vocabulary_size
                features[index, slot] += 1
        projected = features @ self.projection
        activated = projected * ndtr(projected)
        centered = activated - activated.mean(axis=1, keepdims=True)
        return (centered / np.sqrt(activated.var(axis=1, keepdims=True) + 1e-5)).astype(np.float32)


class RandomFourierFeatures:
    def __init__(self, config: Config):
        self.config = config
        gamma = config.rff_gamma if config.rff_gamma is not None else 1 / config.embedding_dim
        generator = np.random.default_rng(config.seed + 1)
        self.weights = generator.normal(
            # 照正态分布生成一个随机权重矩阵，并保存到 self.weights 中。
            0, np.sqrt(2 * gamma), (config.embedding_dim, config.rff_dim),
        ).astype(np.float32)
        # 随机生成一组相位参数，并将它们保存到 self.phase 中，供后续RFF特征转换使用。
        # RFF后面会使用余弦函数，而余弦函数每经过 \(2\pi\) 就会重复一次。
        self.phase = generator.uniform(0, 2 * np.pi, config.rff_dim).astype(np.float32)

    def transform(self, embeddings):
        return (np.sqrt(2 / self.config.rff_dim) * np.cos(embeddings @ self.weights + self.phase)).astype(np.float32)
