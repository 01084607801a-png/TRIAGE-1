# -*- coding: utf-8 -*-
"""
TRIAGE-1 로깅 설정

기능:
- 파일 로깅 (로테이션: 10MB, 10개 백업)
- 에러 파일 로깅 (에러만)
- 콘솔 로깅 (INFO 레벨)
- 포매터 설정 (타임스탐프, 레벨, 메시지)
"""

import logging
import logging.handlers
from pathlib import Path


def setup_logging(app=None):
    """
    애플리케이션 로깅 설정
    
    Args:
        app: Flask 앱 인스턴스 (선택사항)
    
    Returns:
        logger 인스턴스
    """
    
    # logs 디렉토리 생성
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    # 루트 로거 설정
    logger = logging.getLogger('triage')
    logger.setLevel(logging.DEBUG)
    
    # 기존 핸들러 제거 (중복 방지)
    logger.handlers.clear()
    
    # 포매터 설정
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # ============================================================
    # 파일 핸들러 (모든 로그)
    # ============================================================
    file_handler = logging.handlers.RotatingFileHandler(
        'logs/app.log',
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # ============================================================
    # 에러 파일 핸들러 (에러만)
    # ============================================================
    error_handler = logging.handlers.RotatingFileHandler(
        'logs/error.log',
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    # ============================================================
    # 콘솔 핸들러
    # ============================================================
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Flask 앱 로거도 설정
    if app:
        app.logger.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.addHandler(console_handler)
    
    logger.info("=" * 60)
    logger.info("TRIAGE-1 Logging Initialized")
    logger.info("=" * 60)
    
    return logger
