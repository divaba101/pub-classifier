#!/usr/bin/env python3
"""
PROGRESS TRACKER - Real-time event streaming for file processing
Transforms file processing into an engaging, observable experience
"""

import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from enum import Enum
import threading

class EventType(Enum):
    """Event types for progress tracking"""
    # File-level events
    FILE_DISCOVERED = "file_discovered"
    FILE_READING = "file_reading"
    FILE_READ_COMPLETE = "file_read_complete"
    FILE_ANALYZING = "file_analyzing"
    FILE_CLASSIFIED = "file_classified"
    FILE_MOVING = "file_moving"
    FILE_MOVED = "file_moved"
    FILE_FAILED = "file_failed"
    FILE_SKIPPED = "file_skipped"
    
    # OCR events
    OCR_REQUIRED = "ocr_required"
    OCR_STARTED = "ocr_started"
    OCR_PROGRESS = "ocr_progress"
    OCR_COMPLETE = "ocr_complete"
    OCR_FAILED = "ocr_failed"
    
    # AI events
    AI_REQUEST_QUEUED = "ai_request_queued"
    AI_REQUEST_PROCESSING = "ai_request_processing"
    AI_RESPONSE_RECEIVED = "ai_response_received"
    AI_CACHE_HIT = "ai_cache_hit"
    
    # Batch events
    BATCH_STARTED = "batch_started"
    BATCH_PROGRESS = "batch_progress"
    BATCH_COMPLETE = "batch_complete"
    BATCH_PAUSED = "batch_paused"
    BATCH_RESUMED = "batch_resumed"
    
    # System events
    SYSTEM_WARNING = "system_warning"
    SYSTEM_ERROR = "system_error"
    SYSTEM_INFO = "system_info"

class EventLevel(Enum):
    """Event importance levels"""
    DEBUG = "debug"      # Verbose only
    INFO = "info"        # Normal visibility
    SUCCESS = "success"  # Positive outcome
    WARNING = "warning"  # Potential issue
    ERROR = "error"      # Failed operation
    CRITICAL = "critical" # System failure

@dataclass
class ProgressEvent:
    """Single progress event"""
    event_type: EventType
    level: EventLevel
    timestamp: str
    message: str
    
    # Optional metadata
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    category: Optional[str] = None
    confidence: Optional[float] = None
    duration_ms: Optional[int] = None
    
    # Progress indicators
    current: Optional[int] = None
    total: Optional[int] = None
    percentage: Optional[float] = None
    
    # Additional data
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        data = {
            'event_type': self.event_type.value,
            'level': self.level.value,
            'timestamp': self.timestamp,
            'message': self.message
        }
        
        # Add optional fields if present
        if self.file_path: data['file_path'] = self.file_path
        if self.file_name: data['file_name'] = self.file_name
        if self.file_size: data['file_size'] = self.file_size
        if self.category: data['category'] = self.category
        if self.confidence is not None: data['confidence'] = round(self.confidence, 3)
        if self.duration_ms: data['duration_ms'] = self.duration_ms
        if self.current is not None: data['current'] = self.current
        if self.total is not None: data['total'] = self.total
        if self.percentage is not None: data['percentage'] = round(self.percentage, 1)
        if self.metadata: data['metadata'] = self.metadata
        
        return data

class ProgressTracker:
    """
    Real-time progress tracker with event streaming
    
    Features:
    - Granular event types for every operation
    - Verbose mode filtering
    - Performance metrics
    - WebSocket-ready event emission
    """
    
    def __init__(self, verbose: bool = False, emit_callback: Optional[Callable] = None):
        """
        Initialize progress tracker
        
        Args:
            verbose: Show debug-level events
            emit_callback: Function to call for each event (e.g., WebSocket emit)
        """
        self.verbose = verbose
        self.emit_callback = emit_callback
        self.start_time = time.time()
        
        # Stats tracking
        self.stats = {
            'total_events': 0,
            'events_by_type': {},
            'events_by_level': {},
            'files_discovered': 0,
            'files_processed': 0,
            'files_successful': 0,
            'files_failed': 0,
            'files_skipped': 0,
            'ocr_operations': 0,
            'ai_requests': 0,
            'ai_cache_hits': 0,
            'total_bytes_processed': 0,
            'avg_processing_time_ms': 0
        }
        
        # Performance tracking
        self.file_timings = []
        self.operation_timings = {}
        
        # Thread safety
        self.lock = threading.Lock()
    
    def emit(self, event: ProgressEvent):
        """Emit a progress event"""
        # Filter debug events if not verbose
        if event.level == EventLevel.DEBUG and not self.verbose:
            return
        
        with self.lock:
            # Update stats
            self.stats['total_events'] += 1
            
            event_type = event.event_type.value
            self.stats['events_by_type'][event_type] = \
                self.stats['events_by_type'].get(event_type, 0) + 1
            
            level = event.level.value
            self.stats['events_by_level'][level] = \
                self.stats['events_by_level'].get(level, 0) + 1
            
            # Track specific metrics
            if event.event_type == EventType.FILE_DISCOVERED:
                self.stats['files_discovered'] += 1
                if event.file_size:
                    self.stats['total_bytes_processed'] += event.file_size
            
            elif event.event_type == EventType.FILE_MOVED:
                self.stats['files_successful'] += 1
                self.stats['files_processed'] += 1
                if event.duration_ms:
                    self.file_timings.append(event.duration_ms)
                    self.stats['avg_processing_time_ms'] = sum(self.file_timings) / len(self.file_timings)
            
            elif event.event_type == EventType.FILE_FAILED:
                self.stats['files_failed'] += 1
                self.stats['files_processed'] += 1
            
            elif event.event_type == EventType.FILE_SKIPPED:
                self.stats['files_skipped'] += 1
            
            elif event.event_type in [EventType.OCR_STARTED, EventType.OCR_COMPLETE]:
                self.stats['ocr_operations'] += 1
            
            elif event.event_type == EventType.AI_REQUEST_PROCESSING:
                self.stats['ai_requests'] += 1
            
            elif event.event_type == EventType.AI_CACHE_HIT:
                self.stats['ai_cache_hits'] += 1
        
        # Emit to callback (WebSocket)
        if self.emit_callback:
            try:
                self.emit_callback('progress_event', event.to_dict())
            except Exception as e:
                print(f"Failed to emit event: {e}")
    
    # ==================== CONVENIENCE METHODS ====================
    
    def file_discovered(self, file_path: str, file_size: int):
        """File was discovered in scan"""
        self.emit(ProgressEvent(
            event_type=EventType.FILE_DISCOVERED,
            level=EventLevel.DEBUG,
            timestamp=datetime.now().isoformat(),
            message=f"Discovered: {Path(file_path).name}",
            file_path=file_path,
            file_name=Path(file_path).name,
            file_size=file_size
        ))
    
    def file_reading(self, file_path: str):
        """Started reading file"""
        self.emit(ProgressEvent(
            event_type=EventType.FILE_READING,
            level=EventLevel.DEBUG,
            timestamp=datetime.now().isoformat(),
            message=f"Reading: {Path(file_path).name}",
            file_path=file_path,
            file_name=Path(file_path).name
        ))
    
    def file_read_complete(self, file_path: str, text_length: int, duration_ms: int):
        """File read successfully"""
        self.emit(ProgressEvent(
            event_type=EventType.FILE_READ_COMPLETE,
            level=EventLevel.DEBUG,
            timestamp=datetime.now().isoformat(),
            message=f"Read complete: {Path(file_path).name} ({text_length} chars)",
            file_path=file_path,
            file_name=Path(file_path).name,
            duration_ms=duration_ms,
            metadata={'text_length': text_length}
        ))
    
    def file_analyzing(self, file_path: str):
        """Started AI analysis"""
        self.emit(ProgressEvent(
            event_type=EventType.FILE_ANALYZING,
            level=EventLevel.INFO,
            timestamp=datetime.now().isoformat(),
            message=f"Analyzing: {Path(file_path).name}",
            file_path=file_path,
            file_name=Path(file_path).name
        ))
    
    def file_classified(self, file_path: str, category: str, confidence: float):
        """File classified successfully"""
        self.emit(ProgressEvent(
            event_type=EventType.FILE_CLASSIFIED,
            level=EventLevel.SUCCESS,
            timestamp=datetime.now().isoformat(),
            message=f"Classified as '{category}' ({int(confidence*100)}%): {Path(file_path).name}",
            file_path=file_path,
            file_name=Path(file_path).name,
            category=category,
            confidence=confidence
        ))
    
    def file_moving(self, file_path: str, category: str):
        """Started moving file"""
        self.emit(ProgressEvent(
            event_type=EventType.FILE_MOVING,
            level=EventLevel.DEBUG,
            timestamp=datetime.now().isoformat(),
            message=f"Moving to {category}/: {Path(file_path).name}",
            file_path=file_path,
            file_name=Path(file_path).name,
            category=category
        ))
    
    def file_moved(self, file_path: str, category: str, total_duration_ms: int):
        """File moved successfully"""
        self.emit(ProgressEvent(
            event_type=EventType.FILE_MOVED,
            level=EventLevel.SUCCESS,
            timestamp=datetime.now().isoformat(),
            message=f"✅ {Path(file_path).name} → {category}/ ({total_duration_ms}ms)",
            file_path=file_path,
            file_name=Path(file_path).name,
            category=category,
            duration_ms=total_duration_ms
        ))
    
    def file_failed(self, file_path: str, error: str):
        """File processing failed"""
        self.emit(ProgressEvent(
            event_type=EventType.FILE_FAILED,
            level=EventLevel.ERROR,
            timestamp=datetime.now().isoformat(),
            message=f"❌ Failed: {Path(file_path).name} - {error}",
            file_path=file_path,
            file_name=Path(file_path).name,
            metadata={'error': error}
        ))
    
    def file_skipped(self, file_path: str, reason: str):
        """File skipped"""
        self.emit(ProgressEvent(
            event_type=EventType.FILE_SKIPPED,
            level=EventLevel.WARNING,
            timestamp=datetime.now().isoformat(),
            message=f"⏭️ Skipped: {Path(file_path).name} - {reason}",
            file_path=file_path,
            file_name=Path(file_path).name,
            metadata={'reason': reason}
        ))
    
    def ocr_required(self, file_path: str):
        """OCR required for file"""
        self.emit(ProgressEvent(
            event_type=EventType.OCR_REQUIRED,
            level=EventLevel.INFO,
            timestamp=datetime.now().isoformat(),
            message=f"📄 OCR required: {Path(file_path).name}",
            file_path=file_path,
            file_name=Path(file_path).name
        ))
    
    def ocr_started(self, file_path: str):
        """OCR processing started"""
        self.emit(ProgressEvent(
            event_type=EventType.OCR_STARTED,
            level=EventLevel.INFO,
            timestamp=datetime.now().isoformat(),
            message=f"🔍 OCR processing: {Path(file_path).name}",
            file_path=file_path,
            file_name=Path(file_path).name
        ))
    
    def ocr_progress(self, file_path: str, current_page: int, total_pages: int):
        """OCR page progress"""
        percentage = (current_page / total_pages) * 100
        self.emit(ProgressEvent(
            event_type=EventType.OCR_PROGRESS,
            level=EventLevel.DEBUG,
            timestamp=datetime.now().isoformat(),
            message=f"OCR page {current_page}/{total_pages}: {Path(file_path).name}",
            file_path=file_path,
            file_name=Path(file_path).name,
            current=current_page,
            total=total_pages,
            percentage=percentage
        ))
    
    def ocr_complete(self, file_path: str, text_length: int, duration_ms: int):
        """OCR completed"""
        self.emit(ProgressEvent(
            event_type=EventType.OCR_COMPLETE,
            level=EventLevel.SUCCESS,
            timestamp=datetime.now().isoformat(),
            message=f"✅ OCR complete: {Path(file_path).name} ({text_length} chars, {duration_ms}ms)",
            file_path=file_path,
            file_name=Path(file_path).name,
            duration_ms=duration_ms,
            metadata={'text_length': text_length}
        ))
    
    def ocr_failed(self, file_path: str, error: str):
        """OCR failed"""
        self.emit(ProgressEvent(
            event_type=EventType.OCR_FAILED,
            level=EventLevel.ERROR,
            timestamp=datetime.now().isoformat(),
            message=f"❌ OCR failed: {Path(file_path).name} - {error}",
            file_path=file_path,
            file_name=Path(file_path).name,
            metadata={'error': error}
        ))
    
    def ai_request_queued(self, file_path: str):
        """AI request queued"""
        self.emit(ProgressEvent(
            event_type=EventType.AI_REQUEST_QUEUED,
            level=EventLevel.DEBUG,
            timestamp=datetime.now().isoformat(),
            message=f"AI request queued: {Path(file_path).name}",
            file_path=file_path,
            file_name=Path(file_path).name
        ))
    
    def ai_request_processing(self, file_path: str):
        """AI processing request"""
        self.emit(ProgressEvent(
            event_type=EventType.AI_REQUEST_PROCESSING,
            level=EventLevel.DEBUG,
            timestamp=datetime.now().isoformat(),
            message=f"🤖 AI analyzing: {Path(file_path).name}",
            file_path=file_path,
            file_name=Path(file_path).name
        ))
    
    def ai_response_received(self, file_path: str, category: str, confidence: float, duration_ms: int):
        """AI response received"""
        self.emit(ProgressEvent(
            event_type=EventType.AI_RESPONSE_RECEIVED,
            level=EventLevel.DEBUG,
            timestamp=datetime.now().isoformat(),
            message=f"AI responded: {category} ({int(confidence*100)}%) in {duration_ms}ms",
            file_path=file_path,
            file_name=Path(file_path).name,
            category=category,
            confidence=confidence,
            duration_ms=duration_ms
        ))
    
    def ai_cache_hit(self, file_path: str):
        """AI cache hit"""
        self.emit(ProgressEvent(
            event_type=EventType.AI_CACHE_HIT,
            level=EventLevel.DEBUG,
            timestamp=datetime.now().isoformat(),
            message=f"⚡ Cache hit: {Path(file_path).name}",
            file_path=file_path,
            file_name=Path(file_path).name
        ))
    
    def batch_started(self, total_files: int):
        """Batch processing started"""
        self.emit(ProgressEvent(
            event_type=EventType.BATCH_STARTED,
            level=EventLevel.INFO,
            timestamp=datetime.now().isoformat(),
            message=f"🚀 Starting batch: {total_files} files",
            total=total_files
        ))
    
    def batch_progress(self, current: int, total: int, success: int, failed: int):
        """Batch progress update"""
        percentage = (current / total) * 100 if total > 0 else 0
        self.emit(ProgressEvent(
            event_type=EventType.BATCH_PROGRESS,
            level=EventLevel.INFO,
            timestamp=datetime.now().isoformat(),
            message=f"Progress: {current}/{total} ({int(percentage)}%) - ✅ {success} ❌ {failed}",
            current=current,
            total=total,
            percentage=percentage,
            metadata={'success': success, 'failed': failed}
        ))
    
    def batch_complete(self, total: int, success: int, failed: int, duration_s: int):
        """Batch completed"""
        self.emit(ProgressEvent(
            event_type=EventType.BATCH_COMPLETE,
            level=EventLevel.SUCCESS,
            timestamp=datetime.now().isoformat(),
            message=f"🎉 Batch complete: {success}/{total} successful in {duration_s}s",
            total=total,
            metadata={'success': success, 'failed': failed, 'duration_s': duration_s}
        ))
    
    def system_warning(self, message: str, **kwargs):
        """System warning"""
        self.emit(ProgressEvent(
            event_type=EventType.SYSTEM_WARNING,
            level=EventLevel.WARNING,
            timestamp=datetime.now().isoformat(),
            message=f"⚠️ {message}",
            metadata=kwargs if kwargs else None
        ))
    
    def system_error(self, message: str, **kwargs):
        """System error"""
        self.emit(ProgressEvent(
            event_type=EventType.SYSTEM_ERROR,
            level=EventLevel.ERROR,
            timestamp=datetime.now().isoformat(),
            message=f"❌ {message}",
            metadata=kwargs if kwargs else None
        ))
    
    def system_info(self, message: str, **kwargs):
        """System info"""
        self.emit(ProgressEvent(
            event_type=EventType.SYSTEM_INFO,
            level=EventLevel.INFO,
            timestamp=datetime.now().isoformat(),
            message=message,
            metadata=kwargs if kwargs else None
        ))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics"""
        with self.lock:
            elapsed_time = time.time() - self.start_time
            
            return {
                **self.stats,
                'elapsed_time_s': int(elapsed_time),
                'files_per_second': round(self.stats['files_processed'] / elapsed_time, 2) if elapsed_time > 0 else 0,
                'avg_file_size_mb': round(self.stats['total_bytes_processed'] / (1024**2) / max(1, self.stats['files_processed']), 2),
                'cache_hit_rate': round(self.stats['ai_cache_hits'] / max(1, self.stats['ai_requests']), 2)
            }
