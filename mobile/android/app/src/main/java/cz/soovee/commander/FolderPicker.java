package cz.soovee.commander;

import android.app.*;
import android.widget.*;
import android.view.*;
import com.chaquo.python.PyObject;
import org.json.*;
import java.util.*;
import java.util.concurrent.Executor;
import java.util.function.Consumer;
import java.util.function.Function;

/** The same destination browser for local storage and authenticated remote folders. */
final class FolderPicker {
    String path="/"; int generation=0;
    final ArrayList<String> directories=new ArrayList<>();
    FolderPicker(Activity activity,PyObject core,Executor worker,String peer,String title,Function<String,String> text,Consumer<String> chosen,Consumer<Exception> error){
        LinearLayout body=new LinearLayout(activity);body.setOrientation(1);body.setPadding(24,12,24,12);
        TextView location=new TextView(activity);location.setTextIsSelectable(true);body.addView(location);
        Button parent=new Button(activity);parent.setText("↑ ..");body.addView(parent);
        ListView list=new ListView(activity);body.addView(list,new LinearLayout.LayoutParams(-1,400));
        AlertDialog dialog=(activity instanceof MainActivity?((MainActivity)activity).dialog():new AlertDialog.Builder(activity)).setTitle(title).setView(body)
            .setNegativeButton(android.R.string.cancel,null).setPositiveButton(text.apply("Use this folder"),(d,w)->chosen.accept(path)).create();
        Runnable[] reload=new Runnable[1];reload[0]=()->{
            location.setText(path+"\n"+text.apply("Loading folders…"));parent.setEnabled(!path.equals("/"));list.setEnabled(false);int request=++generation;String requested=path;
            if(dialog.isShowing())dialog.getButton(-1).setEnabled(false);
            worker.execute(()->{try{
                JSONArray values=new JSONArray(peer.isEmpty()?core.callAttr("browse_local_path",requested).toString():core.callAttr("browse",peer,requested).toString());
                ArrayList<String> names=new ArrayList<>();for(int n=0;n<values.length();n++)if(values.getJSONObject(n).optBoolean("directory"))names.add(values.getJSONObject(n).getString("name"));
                activity.runOnUiThread(()->{if(!dialog.isShowing()||request!=generation)return;directories.clear();directories.addAll(names);
                    list.setAdapter(new ArrayAdapter<>(activity,android.R.layout.simple_list_item_1,names));list.setEnabled(true);location.setText(path);dialog.getButton(-1).setEnabled(!path.equals("/"));});
            }catch(Exception exception){activity.runOnUiThread(()->{if(dialog.isShowing()&&request==generation)error.accept(exception);});}});
        };
        parent.setOnClickListener(v->{int slash=path.lastIndexOf('/');path=slash<=0?"/":path.substring(0,slash);reload[0].run();});
        list.setOnItemClickListener((adapter,view,index,id)->{path=(path.equals("/")?"/":path+"/")+directories.get(index);reload[0].run();});
        dialog.setOnShowListener(d->reload[0].run());dialog.show();
    }
}
