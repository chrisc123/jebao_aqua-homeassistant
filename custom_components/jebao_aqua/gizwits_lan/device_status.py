# device_status.py
from dataclasses import dataclass, field
import time
from typing import Dict, Any

@dataclass
class DeviceStatus:
    """
    Represents a snapshot of device status at a point in time.
    
    Attributes:
        data: Dict mapping attribute names to their current values
        timestamp: When this status was received/created
        last_pong: Time of last pong response (for availability tracking)
    
    Methods:
        age(): How old this status data is
        pong_age(): How long since last pong response
    """
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    last_pong: float = field(default_factory=time.time)

    def age(self) -> float:
        """
        Return how many seconds have passed since this status snapshot was created.
        """
        return time.time() - self.timestamp

    def pong_age(self) -> float:
        """
        Return how many seconds have passed since the last pong response.
        Can be used to determine if device is still responsive.
        """
        return time.time() - self.last_pong

