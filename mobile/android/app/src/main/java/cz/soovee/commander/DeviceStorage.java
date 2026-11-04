package cz.soovee.commander;

import android.content.Context;
import android.content.pm.PackageManager;
import android.Manifest;
import android.os.Build;
import android.os.Environment;
import android.os.storage.StorageManager;
import android.os.storage.StorageVolume;
import org.json.*;
import java.io.File;
import java.util.*;

/** Only OS-granted shared volumes. App-private data and other apps stay protected. */
final class DeviceStorage {
    static boolean permitted(Context context){
        return Build.VERSION.SDK_INT>=30?Environment.isExternalStorageManager():
            context.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)==PackageManager.PERMISSION_GRANTED;
    }
    static JSONObject root(String key,String name,File path,boolean writable)throws JSONException{
        return new JSONObject().put("key",key).put("name",name).put("path",path.getAbsolutePath()).put("writable",writable);
    }
    static JSONArray roots(Context context)throws JSONException{
        JSONArray result=new JSONArray();result.put(root("app","Shared",new File(context.getFilesDir(),"Shared"),true));
        if(!permitted(context))return result;
        HashSet<String> paths=new HashSet<>();
        StorageManager manager=(StorageManager)context.getSystemService(Context.STORAGE_SERVICE);
        if(Build.VERSION.SDK_INT>=30){
            for(StorageVolume volume:manager.getStorageVolumes()){
                File path=volume.getDirectory();
                if(path==null||!path.isDirectory()||!path.canRead()||!paths.add(path.getAbsolutePath()))continue;
                String key=volume.isPrimary()?"internal":"usb-"+volume.getUuid();
                String name=volume.isPrimary()?"Internal storage":volume.getDescription(context);
                name=name.replace('/','_').replace('\\','_');
                if(!volume.isPrimary())name+=" ("+volume.getUuid()+")";
                result.put(root(key,name,path,path.canWrite()));
            }
        }else{
            File path=Environment.getExternalStorageDirectory();
            if(path.isDirectory())result.put(root("internal","Internal storage",path,path.canWrite()));
            for(File external:context.getExternalFilesDirs(null)){
                if(external==null)continue;File volume=external;
                for(int n=0;n<4&&volume!=null;n++)volume=volume.getParentFile();
                if(volume==null||volume.equals(path)||!volume.getAbsolutePath().startsWith("/storage/")||!volume.canRead()||!paths.add(volume.getAbsolutePath()))continue;
                result.put(root("usb-"+volume.getName(),"USB "+volume.getName(),volume,volume.canWrite()));
            }
        }
        return result;
    }
}
