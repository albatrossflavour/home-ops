#!/usr/bin/env python3
"""
Overseerr to Sonarr/Radarr Reconciliation Tool

This script identifies approved Overseerr requests that are missing from
Sonarr/Radarr and optionally re-submits them.

Usage:
    python overseerr-reconcile.py --check          # Dry run - identify missing items
    python overseerr-reconcile.py --sync           # Re-submit missing requests
    python overseerr-reconcile.py --check --type tv    # Check only TV shows
    python overseerr-reconcile.py --check --type movie # Check only movies
"""

import argparse
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class MediaType(Enum):
    """Media type enum"""

    MOVIE = "movie"
    TV = "tv"


class RequestStatus(Enum):
    """Overseerr request status"""

    PENDING_APPROVAL = 1
    APPROVED = 2
    DECLINED = 3


@dataclass
class OverseerrRequest:
    """Overseerr request data"""

    id: int
    media_type: MediaType
    title: str
    tmdb_id: int
    tvdb_id: Optional[int]
    status: int
    requested_by: str
    created_at: str


@dataclass
class Config:
    """Application configuration"""

    overseerr_url: str
    overseerr_api_key: str
    sonarr_url: str
    sonarr_api_key: str
    radarr_url: str
    radarr_api_key: str


class APIClient:
    """Base API client with retry logic"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create session with retry logic"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """GET request with error handling"""
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        try:
            response = self.session.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error calling {url}: {e}", file=sys.stderr)
            raise

    def post(self, endpoint: str, data: Dict) -> Dict:
        """POST request with error handling"""
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        try:
            response = self.session.post(url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error calling {url}: {e}", file=sys.stderr)
            raise

    def _get_headers(self) -> Dict[str, str]:
        """Override in subclasses"""
        raise NotImplementedError


class OverseerrClient(APIClient):
    """Overseerr API client"""

    def _get_headers(self) -> Dict[str, str]:
        return {"X-Api-Key": self.api_key, "Content-Type": "application/json"}

    def get_requests(
        self, status: Optional[RequestStatus] = None, debug: bool = False
    ) -> List[OverseerrRequest]:
        """Get all requests, optionally filtered by status"""
        all_requests = []
        page = 1

        while True:
            params: Dict[str, int] = {"take": 50, "skip": (page - 1) * 50}
            if status:
                params["filter"] = "approved"  # type: ignore[assignment]

            data = self.get("/api/v1/request", params=params)

            if debug and page == 1 and data.get("results"):
                import json

                print("\n🔍 Debug: First request structure:", file=sys.stderr)
                print(json.dumps(data["results"][0], indent=2), file=sys.stderr)
                print()

            if not data.get("results"):
                break

            for req in data["results"]:
                try:
                    media_type = (
                        MediaType.MOVIE if req["type"] == "movie" else MediaType.TV
                    )

                    # Handle different title fields - check multiple possible locations
                    title = None

                    # Try direct title/name fields
                    if "media" in req:
                        media = req["media"]
                        title = (
                            media.get("title")
                            or media.get("name")
                            or media.get("originalTitle")
                            or media.get("originalName")
                        )
                        tmdb_id = media.get("tmdbId", 0)
                        tvdb_id = media.get("tvdbId")
                    else:
                        # Fallback to root level
                        title = req.get("title") or req.get("name")
                        tmdb_id = req.get("tmdbId", 0)
                        tvdb_id = req.get("tvdbId")

                    # Last resort: use ID as title
                    if not title:
                        title = f"Request #{req['id']}"

                    all_requests.append(
                        OverseerrRequest(
                            id=req["id"],
                            media_type=media_type,
                            title=title,
                            tmdb_id=tmdb_id,
                            tvdb_id=tvdb_id,
                            status=req["status"],
                            requested_by=req.get("requestedBy", {}).get(
                                "displayName", "Unknown"
                            ),
                            created_at=req.get("createdAt", ""),
                        )
                    )
                except (KeyError, TypeError) as e:
                    print(
                        f"  ⚠️  Skipping malformed request {req.get('id', 'unknown')}: {e}",
                        file=sys.stderr,
                    )
                    continue

            if data["pageInfo"]["pages"] <= page:
                break
            page += 1

        # Filter by status if specified
        if status:
            all_requests = [r for r in all_requests if r.status == status.value]

        return all_requests

    def retry_request(self, request_id: int) -> bool:
        """Retry sending a request to Sonarr/Radarr"""
        try:
            self.post(f"/api/v1/request/{request_id}/retry", {})
            return True
        except Exception as e:
            print(f"Failed to retry request {request_id}: {e}", file=sys.stderr)
            return False


class SonarrClient(APIClient):
    """Sonarr API client"""

    def _get_headers(self) -> Dict[str, str]:
        return {"X-Api-Key": self.api_key, "Content-Type": "application/json"}

    def get_series(self) -> List[Dict]:
        """Get all series in Sonarr"""
        return self.get("/api/v3/series")  # type: ignore[return-value]

    def has_series(self, tvdb_id: int) -> bool:
        """Check if series exists in Sonarr by TVDB ID"""
        series_list = self.get_series()
        return any(s.get("tvdbId") == tvdb_id for s in series_list)

    def lookup_series(self, tvdb_id: int) -> Optional[Dict]:
        """Lookup series by TVDB ID"""
        try:
            results = self.get(f"/api/v3/series/lookup?term=tvdb:{tvdb_id}")
            return results[0] if results else None  # type: ignore[return-value]
        except Exception:
            return None

    def get_quality_profiles(self) -> List[Dict]:
        """Get quality profiles"""
        return self.get("/api/v3/qualityprofile")  # type: ignore[return-value]

    def get_root_folders(self) -> List[Dict]:
        """Get root folders"""
        return self.get("/api/v3/rootfolder")  # type: ignore[return-value]

    def add_series(
        self, tvdb_id: int, quality_profile_id: int = None, root_folder: str = None
    ) -> bool:
        """Add series to Sonarr"""
        try:
            # Lookup series info
            series_info = self.lookup_series(tvdb_id)
            if not series_info:
                print(
                    f"    Could not find series info for TVDB: {tvdb_id}",
                    file=sys.stderr,
                )
                return False

            # Auto-detect settings if not provided
            if quality_profile_id is None:
                profiles = self.get_quality_profiles()
                quality_profile_id = profiles[0]["id"] if profiles else 1

            if root_folder is None:
                folders = self.get_root_folders()
                root_folder = folders[0]["path"] if folders else "/media"

            # Prepare add request
            series_info.update(
                {
                    "qualityProfileId": quality_profile_id,
                    "rootFolderPath": root_folder,
                    "monitored": True,
                    "addOptions": {"searchForMissingEpisodes": True},
                }
            )

            self.post("/api/v3/series", series_info)
            return True
        except requests.exceptions.HTTPError as e:
            if e.response is not None:
                print(
                    f"    Error adding series: {e.response.status_code} - {e.response.text[:200]}",
                    file=sys.stderr,
                )
            else:
                print(f"    Error adding series: {e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"    Error adding series: {e}", file=sys.stderr)
            return False


class RadarrClient(APIClient):
    """Radarr API client"""

    def _get_headers(self) -> Dict[str, str]:
        return {"X-Api-Key": self.api_key, "Content-Type": "application/json"}

    def get_movies(self) -> List[Dict]:
        """Get all movies in Radarr"""
        return self.get("/api/v3/movie")  # type: ignore[return-value]

    def has_movie(self, tmdb_id: int) -> bool:
        """Check if movie exists in Radarr by TMDB ID"""
        movies = self.get_movies()
        return any(m.get("tmdbId") == tmdb_id for m in movies)

    def lookup_movie(self, tmdb_id: int) -> Optional[Dict]:
        """Lookup movie by TMDB ID"""
        try:
            results = self.get(f"/api/v3/movie/lookup/tmdb?tmdbId={tmdb_id}")
            return results if isinstance(results, dict) else None  # type: ignore[return-value]
        except Exception:
            return None

    def get_quality_profiles(self) -> List[Dict]:
        """Get quality profiles"""
        return self.get("/api/v3/qualityprofile")  # type: ignore[return-value]

    def get_root_folders(self) -> List[Dict]:
        """Get root folders"""
        return self.get("/api/v3/rootfolder")  # type: ignore[return-value]

    def add_movie(
        self, tmdb_id: int, quality_profile_id: int = None, root_folder: str = None
    ) -> bool:
        """Add movie to Radarr"""
        try:
            # Lookup movie info
            movie_info = self.lookup_movie(tmdb_id)
            if not movie_info:
                print(
                    f"    Could not find movie info for TMDB: {tmdb_id}",
                    file=sys.stderr,
                )
                return False

            # Auto-detect settings if not provided
            if quality_profile_id is None:
                profiles = self.get_quality_profiles()
                quality_profile_id = profiles[0]["id"] if profiles else 1

            if root_folder is None:
                folders = self.get_root_folders()
                root_folder = folders[0]["path"] if folders else "/movies"

            # Prepare add request with required fields
            add_data = {
                "title": movie_info.get("title"),
                "year": movie_info.get("year"),
                "tmdbId": movie_info.get("tmdbId"),
                "qualityProfileId": quality_profile_id,
                "rootFolderPath": root_folder,
                "monitored": True,
                "addOptions": {"searchForMovie": True},
            }

            # Include optional fields if present
            if "images" in movie_info:
                add_data["images"] = movie_info["images"]
            if "titleSlug" in movie_info:
                add_data["titleSlug"] = movie_info["titleSlug"]

            self.post("/api/v3/movie", add_data)
            return True
        except requests.exceptions.HTTPError as e:
            if e.response is not None:
                print(
                    f"    Error adding movie: {e.response.status_code} - {e.response.text[:200]}",
                    file=sys.stderr,
                )
            else:
                print(f"    Error adding movie: {e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"    Error adding movie: {e}", file=sys.stderr)
            return False


class ReconciliationService:
    """Service to reconcile Overseerr requests with Sonarr/Radarr"""

    def __init__(self, config: Config):
        self.overseerr = OverseerrClient(config.overseerr_url, config.overseerr_api_key)
        self.sonarr = SonarrClient(config.sonarr_url, config.sonarr_api_key)
        self.radarr = RadarrClient(config.radarr_url, config.radarr_api_key)

    def find_missing_requests(
        self,
        media_type: Optional[MediaType] = None,
        debug: bool = False,
        sync_mode: bool = False,
    ) -> List[OverseerrRequest]:
        """Find approved requests missing from Sonarr/Radarr"""
        print("🔍 Fetching approved requests from Overseerr...")
        requests = self.overseerr.get_requests(
            status=RequestStatus.APPROVED, debug=debug
        )

        if media_type:
            requests = [r for r in requests if r.media_type == media_type]

        print(f"📋 Found {len(requests)} approved requests")

        missing = []
        success_count = 0
        fail_count = 0

        mode_text = "Checking and adding" if sync_mode else "Checking"
        print(f"\n🔎 {mode_text} {len(requests)} requests against Sonarr/Radarr...")

        for i, req in enumerate(requests, 1):
            if i % 20 == 0:
                print(
                    f"  Progress: {i}/{len(requests)}..."
                    + (
                        f" ({success_count} added, {fail_count} failed)"
                        if sync_mode
                        else ""
                    )
                )

            if req.media_type == MediaType.MOVIE:
                if not self.radarr.has_movie(req.tmdb_id):
                    title = self._get_media_title(
                        req.media_type, req.tmdb_id, req.title
                    )

                    if sync_mode:
                        # Add immediately
                        print(f"  📤 Adding movie: {title}...", end=" ", flush=True)
                        if self.radarr.add_movie(req.tmdb_id):
                            print("✅")
                            success_count += 1
                        else:
                            print("❌")
                            fail_count += 1
                            missing.append(req)  # Track failures
                    else:
                        # Just report
                        missing.append(req)
                        print(
                            f"  ❌ Movie missing: {title} (TMDB: {req.tmdb_id}, Requested: {req.created_at[:10]})"
                        )

            elif req.media_type == MediaType.TV:
                if req.tvdb_id and not self.sonarr.has_series(req.tvdb_id):
                    title = self._get_media_title(
                        req.media_type, req.tvdb_id, req.title, use_tvdb=True
                    )

                    if sync_mode:
                        # Add immediately
                        print(f"  📤 Adding TV show: {title}...", end=" ", flush=True)
                        if self.sonarr.add_series(req.tvdb_id):
                            print("✅")
                            success_count += 1
                        else:
                            print("❌")
                            fail_count += 1
                            missing.append(req)  # Track failures
                    else:
                        # Just report
                        missing.append(req)
                        print(
                            f"  ❌ TV show missing: {title} (TVDB: {req.tvdb_id}, Requested: {req.created_at[:10]})"
                        )
                elif not req.tvdb_id and not sync_mode:
                    print(f"  ⚠️  No TVDB ID for: {req.title} - cannot verify")

        if sync_mode:
            print(f"\n✅ Sync complete: {success_count} added, {fail_count} failed")

        return missing

    def _get_media_title(
        self,
        media_type: MediaType,
        media_id: int,
        fallback: str,
        use_tvdb: bool = False,
    ) -> str:
        """Fetch media title from Overseerr"""
        try:
            endpoint = (
                f"/api/v1/{'tv' if media_type == MediaType.TV else 'movie'}/{media_id}"
            )
            data = self.overseerr.get(endpoint)
            return data.get("title") or data.get("name") or fallback
        except Exception:
            return fallback

    def sync_missing_requests(
        self,
        missing_requests: List[OverseerrRequest],
        sonarr_quality_profile: int = None,
        radarr_quality_profile: int = None,
        sonarr_root: str = None,
        radarr_root: str = None,
    ) -> int:
        """Add missing requests directly to Sonarr/Radarr"""
        if not missing_requests:
            print("✅ No missing requests to sync!")
            return 0

        print(
            f"\n🔄 Adding {len(missing_requests)} missing items directly to Sonarr/Radarr..."
        )

        success_count = 0
        for req in missing_requests:
            title = self._get_media_title(
                req.media_type,
                req.tmdb_id if req.media_type == MediaType.MOVIE else req.tvdb_id,
                req.title,
            )
            print(f"  📤 Adding: {title}...", end=" ")

            try:
                if req.media_type == MediaType.MOVIE:
                    if self.radarr.add_movie(
                        req.tmdb_id, radarr_quality_profile, radarr_root
                    ):
                        print("✅")
                        success_count += 1
                    else:
                        print("❌")
                elif req.media_type == MediaType.TV and req.tvdb_id:
                    if self.sonarr.add_series(
                        req.tvdb_id, sonarr_quality_profile, sonarr_root
                    ):
                        print("✅")
                        success_count += 1
                    else:
                        print("❌")
                else:
                    print("⚠️  No TVDB ID")
            except Exception as e:
                print(f"❌ ({e})")

        return success_count


def load_config() -> Config:
    """Load configuration from environment or prompt user"""
    import os

    # Try to load from environment variables
    overseerr_url = os.getenv(
        "OVERSEERR_URL", "http://overseerr.media.svc.cluster.local:5055"
    )
    overseerr_api_key = os.getenv("OVERSEERR_API_KEY", "")
    sonarr_url = os.getenv("SONARR_URL", "http://sonarr.media.svc.cluster.local:8989")
    sonarr_api_key = os.getenv("SONARR_API_KEY", "")
    radarr_url = os.getenv("RADARR_URL", "http://radarr.media.svc.cluster.local:7878")
    radarr_api_key = os.getenv("RADARR_API_KEY", "")

    # Prompt for missing values
    if not overseerr_api_key:
        overseerr_api_key = input("Overseerr API Key: ").strip()
    if not sonarr_api_key:
        sonarr_api_key = input("Sonarr API Key: ").strip()
    if not radarr_api_key:
        radarr_api_key = input("Radarr API Key: ").strip()

    return Config(
        overseerr_url=overseerr_url,
        overseerr_api_key=overseerr_api_key,
        sonarr_url=sonarr_url,
        sonarr_api_key=sonarr_api_key,
        radarr_url=radarr_url,
        radarr_api_key=radarr_api_key,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile Overseerr requests with Sonarr/Radarr"
    )
    parser.add_argument(
        "--check", action="store_true", help="Check for missing requests (dry run)"
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Re-submit missing requests to Sonarr/Radarr",
    )
    parser.add_argument(
        "--type", choices=["movie", "tv"], help="Filter by media type (movie or tv)"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug output showing API responses"
    )

    args = parser.parse_args()

    if not args.check and not args.sync:
        parser.print_help()
        sys.exit(1)

    # Load configuration
    try:
        config = load_config()
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(0)

    # Initialize service
    service = ReconciliationService(config)

    # Filter by media type if specified
    media_type = None
    if args.type:
        media_type = MediaType.MOVIE if args.type == "movie" else MediaType.TV

    # Find missing requests (and add them if sync mode)
    try:
        if args.sync:
            # In sync mode, ask for confirmation first
            confirm = input(
                "\n⚠️  This will add missing items to Sonarr/Radarr as they're found. Proceed? (yes/no): "
            )
            if confirm.lower() not in ["yes", "y"]:
                print("Cancelled by user")
                sys.exit(0)

            # Run in sync mode - adds as it goes
            failed = service.find_missing_requests(
                media_type, debug=args.debug, sync_mode=True
            )

            # Summary
            print(f"\n{'=' * 60}")
            if failed:
                print(f"⚠️  {len(failed)} item(s) failed to add - review errors above")
                print(f"{'=' * 60}")
            else:
                print("✅ All missing items added successfully!")
                print(f"{'=' * 60}")
        else:
            # Check mode - just report
            missing = service.find_missing_requests(
                media_type, debug=args.debug, sync_mode=False
            )

            # Summary
            print(f"\n{'=' * 60}")
            print(f"📊 Summary: {len(missing)} missing request(s) found")
            print(f"{'=' * 60}")

            if missing:
                print("\nRun with --sync to add these items to Sonarr/Radarr")

    except Exception as e:
        print(f"\n❌ Failed to process requests: {e}", file=sys.stderr)
        if args.debug:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
