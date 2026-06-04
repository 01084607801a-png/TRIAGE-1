# -*- coding: utf-8 -*-
"""
TRIAGE-1 외부 API 호출 클라이언트

지수 백오프를 사용한 자동 재시도 로직 포함
- HTTP 500/502/503/504: 재시도
- Timeout: 재시도
- ConnectionError: 재시도
"""

import requests
import time
import logging

logger = logging.getLogger(__name__)


class APIClient:
    """
    외부 API 호출 클라이언트 (재시도 로직 포함)
    
    재시도 조건:
    - HTTP 429, 500, 502, 503, 504
    - requests.Timeout
    - requests.ConnectionError
    
    재시도 정책:
    - 최대 3회 시도
    - 지수 백오프: 1초, 2초, 4초
    """
    
    def __init__(self, max_retries: int = 3, timeout: float = 5.0):
        """
        Args:
            max_retries: 최대 시도 횟수 (기본 3)
            timeout: 연결 타임아웃 (초, 기본 5)
        """
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()
    
    def get(self, url: str, params: dict = None, headers: dict = None) -> requests.Response:
        """
        GET 요청 (지수 백오프 재시도)
        
        Args:
            url: 요청 URL
            params: 쿼리 파라미터
            headers: HTTP 헤더
        
        Returns:
            requests.Response 객체 또는 None (모든 재시도 실패 시)
        
        예외:
            None - 모든 예외를 잡고 로그만 기록
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    f"API call attempt {attempt+1}/{self.max_retries}",
                    extra={'url': url, 'attempt': attempt+1}
                )
                
                resp = self.session.get(
                    url,
                    params=params,
                    headers=headers or {},
                    timeout=self.timeout
                )
                
                # ====================================================
                # HTTP 200: 성공
                # ====================================================
                if resp.status_code == 200:
                    logger.debug(f"API call succeeded: {url}")
                    return resp
                
                # ====================================================
                # HTTP 429/500/502/503/504: 재시도 가능
                # ====================================================
                elif resp.status_code in [429, 500, 502, 503, 504]:
                    logger.warning(
                        f"API call failed with HTTP {resp.status_code}, retrying...",
                        extra={'url': url, 'status': resp.status_code, 'attempt': attempt+1}
                    )
                    last_exception = Exception(f"HTTP {resp.status_code}")
                    
                    if attempt < self.max_retries - 1:
                        wait_time = 2 ** attempt  # 1, 2, 4초
                        logger.debug(f"Waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                    continue
                
                # ====================================================
                # 기타 HTTP 오류: 재시도 불가능
                # ====================================================
                else:
                    logger.error(
                        f"API call failed with HTTP {resp.status_code}",
                        extra={
                            'url': url,
                            'status': resp.status_code,
                            'body_preview': resp.text[:200]
                        }
                    )
                    return None
            
            # ====================================================
            # Timeout: 재시도
            # ====================================================
            except requests.Timeout as e:
                logger.warning(
                    f"API call timeout (attempt {attempt+1}/{self.max_retries})",
                    extra={'url': url, 'timeout': self.timeout, 'error': str(e)}
                )
                last_exception = e
                
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.debug(f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                continue
            
            # ====================================================
            # ConnectionError: 재시도
            # ====================================================
            except requests.ConnectionError as e:
                logger.warning(
                    f"API connection error (attempt {attempt+1}/{self.max_retries})",
                    extra={'url': url, 'error': str(e)}
                )
                last_exception = e
                
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.debug(f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                continue
            
            # ====================================================
            # 예상치 못한 오류
            # ====================================================
            except Exception as e:
                logger.exception(f"Unexpected error in API call")
                return None
        
        # ====================================================
        # 모든 재시도 실패
        # ====================================================
        logger.error(
            f"API call failed after {self.max_retries} attempts",
            extra={'url': url, 'last_error': str(last_exception)}
        )
        return None
    
    def close(self):
        """세션 종료"""
        self.session.close()
