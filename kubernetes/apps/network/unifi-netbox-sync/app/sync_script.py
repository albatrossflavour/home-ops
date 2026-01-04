#!/usr/bin/env python3
# mypy: ignore-errors
"""
UniFi to NetBox Sync Script
Syncs UniFi devices (UDM Pro compatible) to NetBox DCIM
"""

import logging
import os
import sys
from typing import Dict, List, Optional

import pynetbox
from unificontrol import UnifiClient

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
LOG = logging.getLogger(__name__)


class UniFiNetBoxSync:
    """Sync UniFi controller data to NetBox"""

    def __init__(self):
        """Initialize connections to UniFi and NetBox"""
        # UniFi connection settings
        self.unifi_host = os.getenv("UNIFI_HOST", "")
        self.unifi_username = os.getenv("UNIFI_USERNAME", "")
        self.unifi_password = os.getenv("UNIFI_PASSWORD", "")
        self.unifi_port = int(os.getenv("UNIFI_PORT", "443"))
        self.unifi_verify_ssl = os.getenv("UNIFI_VERIFY_SSL", "false").lower() == "true"
        self.is_udm_pro = os.getenv("UNIFI_IS_UDM_PRO", "true").lower() == "true"

        # NetBox connection settings
        self.netbox_url = os.getenv("NETBOX_URL", "")
        self.netbox_token = os.getenv("NETBOX_TOKEN", "")
        self.netbox_verify_ssl = (
            os.getenv("NETBOX_VERIFY_SSL", "false").lower() == "true"
        )

        # NetBox configuration
        self.netbox_site_slug = os.getenv("NETBOX_SITE_SLUG", "home")
        self.netbox_manufacturer_name = os.getenv("NETBOX_MANUFACTURER", "Ubiquiti")
        self.sync_tag = os.getenv("SYNC_TAG", "unifi-sync")

        # Initialize clients
        self.unifi = None
        self.netbox = None
        self.site = None
        self.manufacturer = None
        self.sync_tag_obj = None

    def connect(self):
        """Establish connections to UniFi and NetBox"""
        LOG.info(f"Connecting to UniFi at {self.unifi_host}:{self.unifi_port}")
        try:
            self.unifi = UnifiClient(
                host=self.unifi_host,
                username=self.unifi_username,
                password=self.unifi_password,
                port=self.unifi_port,
                site="default",
            )
            LOG.info("Successfully connected to UniFi")
        except Exception as e:
            LOG.error(f"Failed to connect to UniFi: {e}")
            raise

        LOG.info(f"Connecting to NetBox at {self.netbox_url}")
        try:
            self.netbox = pynetbox.api(self.netbox_url, token=self.netbox_token)
            if not self.netbox_verify_ssl:
                import requests

                session = requests.Session()
                session.verify = False
                self.netbox.http_session = session
                import urllib3

                urllib3.disable_warnings()
            LOG.info("Successfully connected to NetBox")
        except Exception as e:
            LOG.error(f"Failed to connect to NetBox: {e}")
            raise

    def ensure_prerequisites(self):
        """Ensure required NetBox objects exist"""
        # Ensure site exists
        LOG.info(f"Ensuring NetBox site '{self.netbox_site_slug}' exists")
        self.site = self.netbox.dcim.sites.get(slug=self.netbox_site_slug)
        if not self.site:
            raise ValueError(
                f"NetBox site '{self.netbox_site_slug}' not found. Please create it first."
            )

        # Ensure manufacturer exists
        LOG.info(f"Ensuring manufacturer '{self.netbox_manufacturer_name}' exists")
        self.manufacturer = self.netbox.dcim.manufacturers.get(
            name=self.netbox_manufacturer_name
        )
        if not self.manufacturer:
            LOG.info(f"Creating manufacturer '{self.netbox_manufacturer_name}'")
            self.manufacturer = self.netbox.dcim.manufacturers.create(
                {
                    "name": self.netbox_manufacturer_name,
                    "slug": self.netbox_manufacturer_name.lower(),
                }
            )

        # Ensure sync tag exists
        LOG.info(f"Ensuring tag '{self.sync_tag}' exists")
        self.sync_tag_obj = self.netbox.extras.tags.get(name=self.sync_tag)
        if not self.sync_tag_obj:
            LOG.info(f"Creating tag '{self.sync_tag}'")
            self.sync_tag_obj = self.netbox.extras.tags.create(
                {
                    "name": self.sync_tag,
                    "slug": self.sync_tag,
                    "color": "2196f3",  # Blue
                }
            )

    def get_or_create_device_type(self, model: str, u_height: int = 1):
        """Get or create a device type for a UniFi model"""
        # Sanitize model for slug
        slug = model.lower().replace(" ", "-").replace("_", "-")

        # Check if device type exists
        device_type = self.netbox.dcim.device_types.get(slug=slug)
        if device_type:
            return device_type

        LOG.info(f"Creating device type for model '{model}'")
        try:
            device_type = self.netbox.dcim.device_types.create(
                {
                    "manufacturer": self.manufacturer.id,
                    "model": model,
                    "slug": slug,
                    "u_height": u_height,
                    "is_full_depth": False,
                }
            )
            return device_type
        except Exception as e:
            LOG.error(f"Failed to create device type '{model}': {e}")
            raise

    def get_or_create_device_role(self, role_name: str) -> object:
        """Get or create a device role"""
        slug = role_name.lower().replace(" ", "-")

        role = self.netbox.dcim.device_roles.get(slug=slug)
        if role:
            return role

        LOG.info(f"Creating device role '{role_name}'")
        try:
            role = self.netbox.dcim.device_roles.create(
                {
                    "name": role_name,
                    "slug": slug,
                    "color": "4caf50",  # Green
                }
            )
            return role
        except Exception as e:
            LOG.error(f"Failed to create device role '{role_name}': {e}")
            raise

    def map_unifi_role(self, device_type: str) -> str:
        """Map UniFi device type to NetBox role"""
        role_mapping = {
            "uap": "Access Point",
            "usw": "Switch",
            "ugw": "Gateway",
            "udm": "Gateway",
            "usg": "Gateway",
            "uxg": "Gateway",
        }

        device_type_lower = device_type.lower()
        for key, role in role_mapping.items():
            if key in device_type_lower:
                return role

        return "Network Device"

    def sync_device(self, unifi_device: Dict) -> Optional[object]:
        """Sync a single UniFi device to NetBox"""
        try:
            name = unifi_device.get("name") or unifi_device.get("mac", "unknown")
            model = unifi_device.get("model", "Unknown")
            mac = unifi_device.get("mac", "")

            LOG.info(f"Syncing device: {name} (model: {model}, MAC: {mac})")

            # Determine role
            device_type_str = unifi_device.get("type", "")
            role_name = self.map_unifi_role(device_type_str or model)
            role = self.get_or_create_device_role(role_name)

            # Get or create device type
            device_type = self.get_or_create_device_type(model)

            # Determine status
            state = unifi_device.get("state", 0)
            status = "active" if state == 1 else "offline"

            # Check if device exists (by MAC as primary key)
            device = None
            if mac:
                # Search for device with this MAC in custom field or comment
                devices = list(self.netbox.dcim.devices.filter(site_id=self.site.id))
                for d in devices:
                    if (
                        hasattr(d, "comments")
                        and mac.lower() in str(d.comments).lower()
                    ):
                        device = d
                        break

            # If not found by MAC, try by name
            if not device:
                device = self.netbox.dcim.devices.get(name=name, site_id=self.site.id)

            # Prepare device data
            device_data = {
                "name": name,
                "device_type": device_type.id,
                "role": role.id,
                "site": self.site.id,
                "status": status,
                "tags": [self.sync_tag_obj.id],
                "comments": f"UniFi MAC: {mac}\nModel: {model}\nType: {device_type_str}\nSynced from UniFi",
            }

            # Add serial if available
            if unifi_device.get("serial"):
                device_data["serial"] = unifi_device["serial"]

            if device:
                # Update existing device
                LOG.info(f"Updating device '{name}'")
                for key, value in device_data.items():
                    setattr(device, key, value)
                device.save()
            else:
                # Create new device
                LOG.info(f"Creating device '{name}'")
                device = self.netbox.dcim.devices.create(device_data)

            # Sync interfaces if device has port table
            if "port_table" in unifi_device:
                self.sync_device_interfaces(device, unifi_device["port_table"])

            return device

        except Exception as e:
            LOG.error(
                f"Failed to sync device {unifi_device.get('name', 'unknown')}: {e}"
            )
            return None

    def sync_device_interfaces(self, netbox_device: object, port_table: List[Dict]):
        """Sync device interfaces/ports"""
        for port in port_table:
            try:
                port_idx = port.get("port_idx", 0)
                name = f"Port {port_idx}" if port_idx else port.get("name", "unknown")

                # Check if interface exists
                interface = self.netbox.dcim.interfaces.get(
                    device_id=netbox_device.id,
                    name=name,
                )

                # Determine interface type
                media = port.get("media", "rj45").upper()
                if_type = "1000base-t" if "rj45" in media.lower() else "other"

                # Check if enabled
                enabled = not port.get("port_poe", False) or port.get("enable", True)

                interface_data = {
                    "device": netbox_device.id,
                    "name": name,
                    "type": if_type,
                    "enabled": enabled,
                    "description": f"UniFi Port {port_idx}",
                }

                # Add MAC if available
                if port.get("mac"):
                    interface_data["mac_address"] = port["mac"]

                if interface:
                    # Update
                    for key, value in interface_data.items():
                        setattr(interface, key, value)
                    interface.save()
                else:
                    # Create
                    self.netbox.dcim.interfaces.create(interface_data)

            except Exception as e:
                LOG.warning(f"Failed to sync interface {name}: {e}")

    def sync_vlans(self):
        """Sync UniFi networks to NetBox VLANs"""
        try:
            LOG.info("Syncing UniFi networks to NetBox VLANs")
            networks = self.unifi.list_networks()

            for network in networks:
                try:
                    vlan_id = network.get("vlan")
                    if not vlan_id:
                        continue

                    name = network.get("name", f"VLAN{vlan_id}")

                    # Check if VLAN exists
                    vlan = self.netbox.ipam.vlans.get(vid=vlan_id, site_id=self.site.id)

                    vlan_data = {
                        "vid": vlan_id,
                        "name": name,
                        "site": self.site.id,
                        "status": "active",
                        "tags": [self.sync_tag_obj.id],
                    }

                    if vlan:
                        LOG.info(f"Updating VLAN {vlan_id} ({name})")
                        for key, value in vlan_data.items():
                            setattr(vlan, key, value)
                        vlan.save()
                    else:
                        LOG.info(f"Creating VLAN {vlan_id} ({name})")
                        self.netbox.ipam.vlans.create(vlan_data)

                except Exception as e:
                    LOG.warning(
                        f"Failed to sync VLAN {network.get('name', 'unknown')}: {e}"
                    )

        except Exception as e:
            LOG.error(f"Failed to sync VLANs: {e}")

    def run(self):
        """Run the sync process"""
        try:
            LOG.info("Starting UniFi to NetBox sync")

            # Connect to both systems
            self.connect()

            # Ensure prerequisites exist
            self.ensure_prerequisites()

            # Sync VLANs first
            self.sync_vlans()

            # Get all devices from UniFi
            LOG.info("Fetching devices from UniFi")
            devices = self.unifi.list_devices()
            LOG.info(f"Found {len(devices)} UniFi devices")

            # Sync each device
            synced_count = 0
            for device in devices:
                if self.sync_device(device):
                    synced_count += 1

            LOG.info(
                f"Sync completed successfully. Synced {synced_count}/{len(devices)} devices"
            )

        except Exception as e:
            LOG.error(f"Sync failed: {e}")
            sys.exit(1)


if __name__ == "__main__":
    sync = UniFiNetBoxSync()
    sync.run()
