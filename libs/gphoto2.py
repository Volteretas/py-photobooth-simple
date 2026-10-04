import os
import time
import subprocess
import shutil
import ctypes
import ctypes.util

RETRIES = 1
GP_CAPTURE_IMAGE = 0
GP_FILE_TYPE_NORMAL = 1

# Locate and load libgphoto2 dynamically across distributions
_found_lib = ctypes.util.find_library('gphoto2')
_candidates = [_found_lib, 'libgphoto2.so.6', 'libgphoto2.so', 'libgphoto2.so.2']
gp = None
for _cand in _candidates:
    if _cand:
        try:
            gp = ctypes.CDLL(_cand)
            break
        except OSError:
            pass

if gp is None:
    raise OSError('Cannot find or load libgphoto2 library.')

PTR = ctypes.pointer

class libgphoto2error(Exception):
    def __init__(self, result, message):
        self.result = result
        self.message = message
    def __str__(self):
        return f"{self.message} ({self.result})"

class CameraFilePath(ctypes.Structure):
    _fields_ = [('name', (ctypes.c_char * 128)), ('folder', (ctypes.c_char * 1024))]

class CameraText(ctypes.Structure):
    _fields_ = [('text', (ctypes.c_char * (32 * 1024)))]

# gPhoto2 C API types and 64-bit safe ABI declarations
gp.gp_context_new.argtypes = []
gp.gp_context_new.restype = ctypes.c_void_p

gp.gp_result_as_string.argtypes = [ctypes.c_int]
gp.gp_result_as_string.restype = ctypes.c_char_p

gp.gp_list_new.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
gp.gp_list_new.restype = ctypes.c_int

gp.gp_camera_autodetect.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p
]
gp.gp_camera_autodetect.restype = ctypes.c_int

gp.gp_list_count.argtypes = [ctypes.c_void_p]
gp.gp_list_count.restype = ctypes.c_int

gp.gp_list_get_name.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
gp.gp_list_get_name.restype = ctypes.c_int

gp.gp_list_get_value.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
gp.gp_list_get_value.restype = ctypes.c_int

gp.gp_list_free.argtypes = [ctypes.c_void_p]
gp.gp_list_free.restype = ctypes.c_int

gp.gp_camera_new.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
gp.gp_camera_new.restype = ctypes.c_int

gp.gp_camera_init.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gp.gp_camera_init.restype = ctypes.c_int

gp.gp_camera_exit.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gp.gp_camera_exit.restype = ctypes.c_int

gp.gp_camera_free.argtypes = [ctypes.c_void_p]
gp.gp_camera_free.restype = ctypes.c_int

gp.gp_camera_get_summary.argtypes = [ctypes.c_void_p, ctypes.POINTER(CameraText), ctypes.c_void_p]
gp.gp_camera_get_summary.restype = ctypes.c_int

gp.gp_camera_get_config.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
gp.gp_camera_get_config.restype = ctypes.c_int

gp.gp_camera_set_config.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
gp.gp_camera_set_config.restype = ctypes.c_int

gp.gp_camera_capture.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(CameraFilePath), ctypes.c_void_p]
gp.gp_camera_capture.restype = ctypes.c_int

gp.gp_camera_capture_preview.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
gp.gp_camera_capture_preview.restype = ctypes.c_int

gp.gp_camera_trigger_capture.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gp.gp_camera_trigger_capture.restype = ctypes.c_int

gp.gp_file_new.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
gp.gp_file_new.restype = ctypes.c_int

gp.gp_camera_file_get.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
gp.gp_camera_file_get.restype = ctypes.c_int

gp.gp_file_open.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
gp.gp_file_open.restype = ctypes.c_int

gp.gp_file_get_data_and_size.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_ulong)]
gp.gp_file_get_data_and_size.restype = ctypes.c_int

gp.gp_file_save.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
gp.gp_file_save.restype = ctypes.c_int

gp.gp_file_ref.argtypes = [ctypes.c_void_p]
gp.gp_file_ref.restype = ctypes.c_int

gp.gp_file_unref.argtypes = [ctypes.c_void_p]
gp.gp_file_unref.restype = ctypes.c_int

gp.gp_file_clean.argtypes = [ctypes.c_void_p]
gp.gp_file_clean.restype = ctypes.c_int

gp.gp_file_free.argtypes = [ctypes.c_void_p]
gp.gp_file_free.restype = ctypes.c_int

gp.gp_widget_ref.argtypes = [ctypes.c_void_p]
gp.gp_widget_ref.restype = ctypes.c_int

gp.gp_widget_unref.argtypes = [ctypes.c_void_p]
gp.gp_widget_unref.restype = ctypes.c_int

gp.gp_widget_get_label.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)]
gp.gp_widget_get_label.restype = ctypes.c_int

gp.gp_widget_get_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)]
gp.gp_widget_get_info.restype = ctypes.c_int

gp.gp_widget_get_type.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
gp.gp_widget_get_type.restype = ctypes.c_int

gp.gp_widget_get_value.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gp.gp_widget_get_value.restype = ctypes.c_int

gp.gp_widget_set_value.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gp.gp_widget_set_value.restype = ctypes.c_int

gp.gp_widget_get_name.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)]
gp.gp_widget_get_name.restype = ctypes.c_int

gp.gp_widget_get_child.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
gp.gp_widget_get_child.restype = ctypes.c_int

gp.gp_widget_count_children.argtypes = [ctypes.c_void_p]
gp.gp_widget_count_children.restype = ctypes.c_int

context = gp.gp_context_new()

def _release_camera_locks():
    """Attempt to unmount/release gphoto2 device locked by GVFS / desktop volume monitor."""
    try:
        if shutil.which('gio'):
            subprocess.run(['gio', 'mount', '-s', 'gphoto2'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        elif shutil.which('gvfs-mount'):
            subprocess.run(['gvfs-mount', '-s', 'gphoto2'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except Exception:
        pass

def check(result):
    if result < 0:
        msg_bytes = gp.gp_result_as_string(result)
        message = msg_bytes.decode('utf-8', errors='replace') if isinstance(msg_bytes, bytes) else str(msg_bytes)
        raise libgphoto2error(result, message)
    return result

def check_unref(result, camfile):
    if result != 0:
        ptr = getattr(camfile, '_ptr', None)
        if ptr and getattr(ptr, 'value', None):
            try:
                gp.gp_file_unref(ptr)
            except Exception:
                pass
        msg_bytes = gp.gp_result_as_string(result)
        message = msg_bytes.decode('utf-8', errors='replace') if isinstance(msg_bytes, bytes) else str(msg_bytes)
        raise libgphoto2error(result, message)

class cameraList():
    def __init__(self):
        self._ptr = ctypes.c_void_p()
        check(gp.gp_list_new(PTR(self._ptr)))
        if not hasattr(gp, 'gp_camera_autodetect'): raise Exception('gphoto2 version is obsolete.')
        gp.gp_camera_autodetect(self._ptr, context)

    def __del__(self):
        if getattr(self, '_ptr', None) and self._ptr.value:
            try:
                gp.gp_list_free(self._ptr)
                self._ptr = ctypes.c_void_p()
            except Exception:
                pass

    def get(self):
        return [(self._get_name(i), self._get_value(i)) for i in range(self.count())]

    def count(self):
        return check(gp.gp_list_count(self._ptr))

    def _get_name(self, index):
        name = ctypes.c_char_p()
        check(gp.gp_list_get_name(self._ptr, int(index), PTR(name)))
        return name.value.decode('utf-8', errors='replace') if name.value else ""

    def _get_value(self, index):
        value = ctypes.c_char_p()
        check(gp.gp_list_get_value(self._ptr, int(index), PTR(value)))
        return value.value.decode('utf-8', errors='replace') if value.value else ""

class camera():
    def __init__(self):
        self._ptr = ctypes.c_void_p()
        check(gp.gp_camera_new(PTR(self._ptr)))
        self._init()
        # Réutilisation du même cameraFile pour le preview (performance)
        self._preview_file = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
        if getattr(self, '_ptr', None) and self._ptr.value:
            try:
                gp.gp_camera_free(self._ptr)
            except Exception:
                pass
            self._ptr = ctypes.c_void_p()

    def close(self):
        if getattr(self, '_preview_file', None):
            try:
                self._preview_file.clean()
                self._preview_file.unref()
            except Exception:
                pass
            self._preview_file = None

        if getattr(self, '_ptr', None) and self._ptr.value:
            try:
                gp.gp_camera_exit(self._ptr, context)
            except Exception:
                pass

    def summary(self):
        txt = CameraText()
        check(gp.gp_camera_get_summary(self._ptr, PTR(txt), context))
        summary = str(txt.text, encoding='ascii')
        r = {}
        for l in summary.splitlines():
            try:
                k, v = l.split(':')
            except ValueError:
                continue
            r[k.strip()] = v.strip()
        return summary

    def get_config(self):
        config = cameraConfig()
        check(gp.gp_camera_get_config(self._ptr, PTR(config._ptr), context))
        return config

    def commit_config(self, config):
        check(gp.gp_camera_set_config(self._ptr, config._ptr, context))

    def capture_image(self, destpath=None):
        # Triffer capture
        path = CameraFilePath()
        ans = 0
        for _ in range(1 + RETRIES):
            ans = gp.gp_camera_capture(self._ptr, GP_CAPTURE_IMAGE, PTR(path), context)
            if ans == 0: break
        check(ans)
        cfile = cameraFile(self._ptr, path.folder, path.name)

        # Save to file
        if destpath:
            cfile.save(destpath.encode('ascii'))
            cfile.unref()
            cfile.clean()
            return None
        else:
            return cfile

    def capture_preview(self, destpath=None):
        if self._preview_file is None: self._preview_file = cameraFile()
        else: self._preview_file.clean()
        
        # Trigger capture
        ans = gp.gp_camera_capture_preview(self._ptr, self._preview_file._ptr, context)
        check(ans)

        # Save to file
        if destpath:
            self._preview_file.save(destpath.encode('ascii'))
            return None
        else:
            return self._preview_file

    def trigger_capture(self):
        check(gp.gp_camera_trigger_capture(self._ptr, context))

    def _init(self):
        ans = 0
        for i in range(1 + RETRIES):
            ans = gp.gp_camera_init(self._ptr, context)
            # Success
            if ans == 0: break

            # Error (Could not lock the device)
            elif ans == -60:
                _release_camera_locks()
                time.sleep(1)
        check(ans)

class cameraFile():
    def __init__(self, cam = None, srcfolder = None, srcfilename = None):
        self._ptr = ctypes.c_void_p()
        check(gp.gp_file_new(PTR(self._ptr)))
        if cam:
            folder_bytes = srcfolder.encode('utf-8') if isinstance(srcfolder, str) else srcfolder
            file_bytes = srcfilename.encode('utf-8') if isinstance(srcfilename, str) else srcfilename
            check_unref(gp.gp_camera_file_get(cam, folder_bytes, file_bytes, GP_FILE_TYPE_NORMAL, self._ptr, context), self)

    def open(self, filename):
        if isinstance(filename, str):
            filename = filename.encode('utf-8')
        check(gp.gp_file_open(self._ptr, filename))

    def get_data(self, auto_clean=True):
        data = ctypes.c_char_p()
        size = ctypes.c_ulong()
        check(gp.gp_file_get_data_and_size(self._ptr, PTR(data), PTR(size)))
        data = ctypes.string_at(data, int(size.value))
        if auto_clean:
            self.clean()
            self.unref()
        return data

    def save(self, filename=None):
        if filename is None: filename = getattr(self, 'name', None)
        if isinstance(filename, str):
            filename = filename.encode('utf-8')
        check(gp.gp_file_save(self._ptr, filename))

    def ref(self):
        if getattr(self, '_ptr', None) and self._ptr.value:
            check(gp.gp_file_ref(self._ptr))

    def unref(self):
        if getattr(self, '_ptr', None) and self._ptr.value:
            ptr = self._ptr
            self._ptr = ctypes.c_void_p()
            check(gp.gp_file_unref(ptr))

    def clean(self):
        if getattr(self, '_ptr', None) and self._ptr.value:
            check(gp.gp_file_clean(self._ptr))

    def __del__(self):
        try:
            if getattr(self, '_ptr', None) and self._ptr.value:
                gp.gp_file_unref(self._ptr)
                self._ptr = ctypes.c_void_p()
        except Exception:
            pass

class cameraConfig():
    def __init__(self):
        self._ptr = ctypes.c_void_p()

    def ref(self):
        if getattr(self, '_ptr', None) and self._ptr.value:
            check(gp.gp_widget_ref(self._ptr))

    def unref(self):
        if getattr(self, '_ptr', None) and self._ptr.value:
            ptr = self._ptr
            self._ptr = ctypes.c_void_p()
            check(gp.gp_widget_unref(ptr))

    def __del__(self):
        try:
            if getattr(self, '_ptr', None) and self._ptr.value:
                gp.gp_widget_unref(self._ptr)
                self._ptr = ctypes.c_void_p()
        except Exception:
            pass

    def get_path(self, path):
        names = path.strip('/').split('/')
        current_widget = self
        for name in names:
            if name == 'main': continue
            current_widget = current_widget._get_child_by_name(name)
            if current_widget is None: return None
        return current_widget

    def list_paths(self, parent_path="/main"):
        children_paths = []
        children = self._get_children()
        for child in children:
            child_path = f"{parent_path}/{child.get_name()}"
            if child._count_children() == 0: children_paths.append(child_path)
            children_paths.extend(child.list_paths(child_path))
        return children_paths

    def get_label(self):
        label = ctypes.c_char_p()
        check(gp.gp_widget_get_label(self._ptr, PTR(label)))
        return label.value.decode('utf-8', errors='replace') if label.value else ""

    def get_info(self):
        info = ctypes.c_char_p()
        check(gp.gp_widget_get_info(self._ptr, PTR(info)))
        return info.value.decode('utf-8', errors='replace') if info.value else ""

    def get_type(self):
        type = ctypes.c_int()
        check(gp.gp_widget_get_type(self._ptr, PTR(type)))
        return type.value

    def get_value(self):
        wtype = self.get_type()
        if wtype in [2, 5, 6]:
            val = ctypes.c_char_p()
            ans = gp.gp_widget_get_value(self._ptr, PTR(val))
            check(ans)
            return val.value.decode('utf-8', errors='replace') if val.value else ""
        elif wtype == 3:
            val = ctypes.c_float()
            ans = gp.gp_widget_get_value(self._ptr, PTR(val))
            check(ans)
            return val.value
        elif wtype in [4, 8]:
            val = ctypes.c_int()
            ans = gp.gp_widget_get_value(self._ptr, PTR(val))
            check(ans)
            return val.value
        else:
            return None

    def set_value(self, value):
        wtype = self.get_type()
        if wtype in [2, 5, 6]:
            if isinstance(value, str):
                val_bytes = value.encode('utf-8')
            elif isinstance(value, bytes):
                val_bytes = value
            else:
                raise libgphoto2error(-1, 'Value should either be a string or bytes')
            val_ptr = ctypes.c_char_p(val_bytes)
        elif wtype == 3:
            val_float = ctypes.c_float(float(value))
            val_ptr = PTR(val_float)
        elif wtype in [4, 8]:
            val_int = ctypes.c_int(int(value))
            val_ptr = PTR(val_int)
        else:
            return
        check(gp.gp_widget_set_value(self._ptr, val_ptr))

    def get_name(self):
        name = ctypes.c_char_p()
        check(gp.gp_widget_get_name(self._ptr, PTR(name)))
        return name.value.decode('utf-8', errors='replace') if name.value else ""

    def _get_child_by_name(self, name):
        for i in range(self._count_children()):
            child = cameraConfig()
            check(gp.gp_widget_get_child(self._ptr, int(i), PTR(child._ptr)))
            check(gp.gp_widget_ref(child._ptr))
            if child.get_name() == name: return child
        return None

    def _count_children(self):
        return gp.gp_widget_count_children(self._ptr)

    def _get_children(self):
        children = []
        for i in range(self._count_children()):
            child = cameraConfig()
            check(gp.gp_widget_get_child(self._ptr, int(i), PTR(child._ptr)))
            check(gp.gp_widget_ref(child._ptr))
            children.append(child)
        return children
