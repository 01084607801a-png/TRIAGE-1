# -*- coding: utf-8 -*-
"""
TRIAGE-1 TTL(Time To Live) 기반 LRU 캐시

특징:
- 시간 기반 만료 (TTL)
- 크기 제한 (LRU 제거)
- 스레드 안전 X (외부에서 Lock 처리)
"""

import time
from collections import OrderedDict
import logging

logger = logging.getLogger(__name__)


class TTLCache:
    """
    TTL 기반 LRU 캐시
    
    - 자동 만료: TTL 초과 항목 제거
    - 크기 제한: max_size 초과 시 가장 오래된 항목 제거
    - OrderedDict 사용: 삽입 순서 유지
    
    주의: 스레드 안전하지 않음 (외부에서 Lock 처리 필요)
    """
    
    def __init__(self, ttl_seconds: int = 300, max_size: int = 1000):
        """
        Args:
            ttl_seconds: Time To Live (초)
            max_size: 최대 항목 수
        """
        self.ttl = ttl_seconds
        self.max_size = max_size
        self.cache = OrderedDict()
        self.timestamps = {}
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0
        }
    
    def get(self, key: str):
        """
        캐시에서 값 조회 (TTL 확인)
        
        Args:
            key: 캐시 키
        
        Returns:
            캐시된 값 또는 None (만료/미존재)
        """
        if key in self.cache:
            # TTL 확인
            age = time.time() - self.timestamps.get(key, 0)
            if age < self.ttl:
                # 캐시 히트 - 최근 사용 항목으로 이동 (LRU)
                self.cache.move_to_end(key)
                self.stats['hits'] += 1
                return self.cache[key]
            else:
                # TTL 만료 - 제거
                del self.cache[key]
                del self.timestamps[key]
                logger.debug(f"Cache entry expired: {key}")
        
        self.stats['misses'] += 1
        return None
    
    def set(self, key: str, value):
        """
        캐시에 값 저장 (크기 제한 적용)
        
        Args:
            key: 캐시 키
            value: 저장할 값
        """
        # 이미 있으면 업데이트 (최신으로 이동)
        if key in self.cache:
            self.cache.move_to_end(key)
        
        self.cache[key] = value
        self.timestamps[key] = time.time()
        
        # 크기 초과 시 가장 오래된 항목 제거 (FIFO)
        while len(self.cache) > self.max_size:
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            del self.timestamps[oldest_key]
            self.stats['evictions'] += 1
            logger.debug(f"Cache eviction: {oldest_key} (LRU limit reached)")
    
    def clear(self):
        """캐시 초기화"""
        self.cache.clear()
        self.timestamps.clear()
        logger.debug("Cache cleared")
    
    def stats_summary(self) -> dict:
        """캐시 통계 반환"""
        total = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total * 100) if total > 0 else 0
        
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'hit_rate_percent': hit_rate,
            'evictions': self.stats['evictions'],
            'ttl_seconds': self.ttl
        }
