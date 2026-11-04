package cz.soovee.commander;

import android.graphics.Typeface;
import android.graphics.drawable.StateListDrawable;
import android.view.*;
import android.widget.*;
import org.json.*;

/** TV overview uses storage tiles and a compact device column, not a wall of buttons. */
final class TvLibraryHome extends LinearLayout {
    final MainActivity host;
    TvLibraryHome(MainActivity host){
        super(host);this.host=host;setOrientation(VERTICAL);
        TextView title=host.label(host.t("TV library"),28);title.setTypeface(null,Typeface.BOLD);addView(title);
        TextView subtitle=host.label(host.t("Your files. All your devices."),14);subtitle.setTextColor(0xffa5b3cc);addView(subtitle);
        LinearLayout body=new LinearLayout(host);LinearLayout storage=host.column();TextView heading=host.label(host.t("Storage and files"),18);heading.setTypeface(null,Typeface.BOLD);storage.addView(heading);
        JSONArray volumes=host.state.optJSONArray("storage");LinearLayout row=null;
        if(volumes!=null)for(int i=0;i<volumes.length();i++){
            JSONObject volume=volumes.optJSONObject(i);String name=volume.optString("name");if(i%2==0){row=new LinearLayout(host);storage.addView(row);}
            LinearLayout tile=host.column();tile.setPadding(host.dp(16),host.dp(14),host.dp(16),host.dp(14));tile.setBackground(host.shape(host.SURFACE,0xff293650));
            LinearLayout top=new LinearLayout(host);View glyph=new FileGlyph(host,true);top.addView(glyph,new LayoutParams(host.dp(40),host.dp(40)));TextView label=host.label(host.t(name),19);label.setTypeface(null,Typeface.BOLD);label.setPadding(host.dp(12),0,0,0);top.addView(label);tile.addView(top);
            long free=volume.optLong("free"),total=volume.optLong("total");TextView detail=host.label(host.t("Free")+" "+android.text.format.Formatter.formatFileSize(host,free)+" / "+android.text.format.Formatter.formatFileSize(host,total),12);detail.setTextColor(0xffa5b3cc);tile.addView(detail);
            ProgressBar capacity=new ProgressBar(host,null,android.R.attr.progressBarStyleHorizontal);capacity.setMax(1000);capacity.setProgress(total>0?(int)(1000.0*(total-free)/total):0);capacity.setProgressTintList(android.content.res.ColorStateList.valueOf(host.CYAN));tile.addView(capacity,new LayoutParams(-1,host.dp(4)));
            tile.setFocusable(true);tile.setClickable(true);tile.setContentDescription(host.t(name)+" · "+detail.getText());tile.setOnFocusChangeListener((v,focused)->tile.setBackground(host.shape(focused?0xff1d3152:host.SURFACE,focused?host.CYAN:0xff293650)));tile.setOnClickListener(v->{host.peer="";host.path="/"+name;host.browserSelection="";host.browse();});
            LayoutParams p=new LayoutParams(0,host.dp(140),1);p.setMargins(0,host.dp(6),host.dp(10),host.dp(10));row.addView(tile,p);
        }
        if(volumes!=null&&volumes.length()%2==1)row.addView(new Space(host),new LayoutParams(0,1,1));
        if(!host.state.optBoolean("storageSharing"))storage.addView(action(host.t("Allow access to device storage…"),host::allowStorage));
        TextView description=host.label(host.t("Pair your phone or computer to manage TV files remotely."),14);description.setTextColor(0xffa5b3cc);description.setPadding(0,host.dp(12),host.dp(12),0);storage.addView(description);
        body.addView(storage,new LayoutParams(0,-2,1));
        LinearLayout devices=host.column();devices.setPadding(host.dp(16),0,0,0);TextView deviceHeading=host.label(host.t("Your devices"),18);deviceHeading.setTypeface(null,Typeface.BOLD);devices.addView(deviceHeading);
        JSONArray peers=host.state.optJSONArray("peers");if(peers!=null)for(int i=0;i<peers.length();i++){JSONObject peer=peers.optJSONObject(i);devices.addView(action(peer.optString("name"),()->{if(host.state.optString("role").equals("controlled")){host.showSettings();return;}host.peer=peer.optString("id");host.path="/";host.browse();}));}
        devices.addView(action(host.t("My QR and pairing code"),host::showPairing));devices.addView(action(host.t("Nearby devices"),host::showNearby));
        body.addView(devices,new LayoutParams(host.dp(240),-2));addView(body);
    }
    View action(String title,Runnable task){Button button=host.button(title,task);button.setTextSize(14);button.setMinHeight(host.dp(44));button.setGravity(Gravity.START|Gravity.CENTER_VERTICAL);LayoutParams p=new LayoutParams(-1,host.dp(48));p.setMargins(0,host.dp(5),0,host.dp(5));button.setLayoutParams(p);return button;}
}
