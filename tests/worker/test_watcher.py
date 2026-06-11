import pytest
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime

from repi.worker import IngestionWorker
from repi.ingestion.log_ingestor import IngestStats
from repi.models.schema import WatcherConfig, WatcherOffset

@pytest.mark.asyncio
async def test_handle_file_change(tmp_path):
    # Setup temp file
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "app.log"
    log_file.write_text("line 1\nline 2\n")
    
    # Mock Worker
    worker = IngestionWorker()
    config = WatcherConfig(
        id=uuid4(),
        service_name="test-service",
        watch_path=str(log_dir),
        enabled=True
    )
    worker.watcher_configs = {str(log_dir): config}
    
    # Mock Session and Ingestor
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_ingestor = AsyncMock()
    mock_ingestor.ingest = AsyncMock(return_value=IngestStats(chunk_count=2))

    # get_session() returns an async context manager that yields mock_session
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    worker.container.get_session = MagicMock(return_value=mock_ctx)
    worker.container.get_ingestor = MagicMock(return_value=mock_ingestor)

    # Mock DB queries — first() must be a plain MagicMock (not AsyncMock)
    mock_result = MagicMock()
    mock_result.first = MagicMock(side_effect=[None, None])
    mock_session.exec = AsyncMock(return_value=mock_result)
    
    # Run handler
    await worker.handle_file_change(str(log_file))
    
    # Assert ingestor called with correct content
    mock_ingestor.ingest.assert_called_once()
    args, _ = mock_ingestor.ingest.call_args
    assert "line 1\nline 2\n" in args[0]
    assert args[1] == "test-service"
    
    # Assert offset updated to file size
    assert worker.offsets[str(log_file)] == log_file.stat().st_size
    
    # Assert session committed
    assert mock_session.commit.call_count >= 1
