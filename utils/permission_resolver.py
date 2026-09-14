# utils/permission_resolver.py
"""
Central permission resolver.
- Looks up owner-defined overrides in `role_permissions` table.
- Falls back to hardcoded defaults in `utils/navigation.py`.
- Cached in-memory for 60 s per (institute_id, role) to avoid DB hits.
"""

from datetime import datetime
from supabase import create_client, Client
import os
import asyncio
import json
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── In-memory cache ──────────────────────────────────────────────────────────────
_perm_cache: dict = {}
_perm_lock = asyncio.Lock()
_CACHE_TTL = 60  # seconds


async def _cache_get(key):
    async with _perm_lock:
        entry = _perm_cache.get(key)
        if entry:
            data, ts = entry
            if (datetime.now() - ts).total_seconds() < _CACHE_TTL:
                return data
    return None


async def _cache_set(key, value):
    async with _perm_lock:
        _perm_cache[key] = (value, datetime.now())


async def invalidate_role_cache(institute_id: str, role: str = None):
    """Call this after owner edits permissions."""
    async with _perm_lock:
        if role:
            _perm_cache.pop(f"{institute_id}:{role}", None)
        else:
            for k in list(_perm_cache.keys()):
                if k.startswith(f"{institute_id}:"):
                    _perm_cache.pop(k, None)


# ── Fetch overrides from DB ──────────────────────────────────────────────────────
async def _fetch_role_row(institute_id: str, role: str):
    """Fetch the role_permissions row for a specific role."""
    try:
        res = await asyncio.to_thread(
            lambda: supabase.table('role_permissions')
            .select('*')
            .eq('institute_id', institute_id)
            .eq('role', role)
            .eq('is_active', True)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"[permission_resolver] fetch error: {e}")
        return None


async def _fetch_all_roles(institute_id: str):
    """Fetch all role overrides for an institute (used by UI + owner)."""
    try:
        res = await asyncio.to_thread(
            lambda: supabase.table('role_permissions')
            .select('*')
            .eq('institute_id', institute_id)
            .order('role')
            .execute()
        )
        return res.data or []
    except Exception as e:
        print(f"[permission_resolver] fetch_all error: {e}")
        return []


async def get_role_overrides(institute_id: str, role: str) -> dict:
    """Return {'menu': {...}, 'route': {...}} for a role, with cache."""
    cache_key = f"{institute_id}:{role}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        return cached

    row = await _fetch_role_row(institute_id, role)
    result = {
        'menu': (row or {}).get('menu_overrides') or {},
        'route': (row or {}).get('route_overrides') or {},
        'display_name': (row or {}).get('display_name'),
        'description': (row or {}).get('description'),
    }

    # Supabase JSONB sometimes comes back as string — normalise
    for k in ('menu', 'route'):
        if isinstance(result[k], str):
            try:
                result[k] = json.loads(result[k])
            except Exception:
                result[k] = {}

    await _cache_set(cache_key, result)
    return result


# ── Public API: check if a role can access a menu / endpoint ─────────────────────
async def can_access_menu(institute_id: str, role: str, menu_key: str) -> bool:
    """
    Owner-editable check for a sidebar menu.
    Returns True/False. Falls back to `None` if not overridden (caller decides).
    """
    overrides = await get_role_overrides(institute_id, role)
    menu_overrides = overrides.get('menu', {})
    if menu_key in menu_overrides:
        return bool(menu_overrides[menu_key])
    return None  # not configured — caller falls back to defaults


async def can_access_route(institute_id: str, role: str, endpoint: str) -> bool:
    """Same as can_access_menu but for a route endpoint."""
    overrides = await get_role_overrides(institute_id, role)
    route_overrides = overrides.get('route', {})
    if endpoint in route_overrides:
        return bool(route_overrides[endpoint])
    return None


# ── Save owner's changes ─────────────────────────────────────────────────────────
async def save_role_permissions(
    institute_id: str,
    role: str,
    menu_overrides: dict,
    route_overrides: dict,
    display_name: str = None,
    description: str = None,
):
    """Upsert a role_permissions row. Returns True/False."""
    try:
        existing = await asyncio.to_thread(
            lambda: supabase.table('role_permissions')
            .select('id')
            .eq('institute_id', institute_id)
            .eq('role', role)
            .execute()
        )

        payload = {
            'institute_id': institute_id,
            'role': role,
            'menu_overrides': menu_overrides or {},
            'route_overrides': route_overrides or {},
            'display_name': display_name,
            'description': description,
            'is_active': True,
            'updated_at': datetime.now().isoformat(),
        }

        if existing.data:
            await asyncio.to_thread(
                lambda: supabase.table('role_permissions')
                .update(payload)
                .eq('id', existing.data[0]['id'])
                .execute()
            )
        else:
            payload['created_at'] = datetime.now().isoformat()
            await asyncio.to_thread(
                lambda: supabase.table('role_permissions')
                .insert(payload)
                .execute()
            )

        await invalidate_role_cache(institute_id, role)
        return True
    except Exception as e:
        print(f"[permission_resolver] save error: {e}")
        return False


async def reset_role_permissions(institute_id: str, role: str):
    """Delete overrides — reverts to defaults."""
    try:
        await asyncio.to_thread(
            lambda: supabase.table('role_permissions')
            .delete()
            .eq('institute_id', institute_id)
            .eq('role', role)
            .execute()
        )
        await invalidate_role_cache(institute_id, role)
        return True
    except Exception as e:
        print(f"[permission_resolver] reset error: {e}")
        return False