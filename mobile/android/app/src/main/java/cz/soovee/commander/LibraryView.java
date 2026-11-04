package cz.soovee.commander;

import android.app.*;
import android.graphics.Typeface;
import android.text.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.*;

/** Responsive native library shared by touch phones and D-pad televisions. */
final class LibraryView extends LinearLayout {
    final MainActivity host;
    final ArrayList<JSONObject> all=new ArrayList<>(), visible=new ArrayList<>();
    final LinkedHashSet<String> selection=new LinkedHashSet<>();
    final GridView grid;
    final TextView summary;
    final LinearLayout commands;
    String query=""; int sort=0;
    boolean tiles;
    LibraryView(MainActivity host,JSONArray entries){
        super(host);this.host=host;setOrientation(VERTICAL);tiles=host.getPreferences(0).getBoolean("file_grid",host.television);
        for(int i=0;i<entries.length();i++)all.add(entries.optJSONObject(i));
        TextView heading=host.label(host.peer.isEmpty()?host.t("Files"):deviceName(),host.television?26:25);heading.setTypeface(null,Typeface.BOLD);addView(heading);
        TextView location=host.label(host.path,13);location.setTextColor(0xffa5b3cc);location.setTextIsSelectable(true);addView(location);
        LinearLayout toolbar=new LinearLayout(host);toolbar.setGravity(Gravity.CENTER_VERTICAL);
        tool(toolbar,"↑",()->{if(!host.path.equals("/"))host.parentFolder();});
        tool(toolbar,"+",()->host.editFileName(null,true));
        tool(toolbar,host.t("Sort"),()->new AlertDialog.Builder(host).setTitle(host.t("Sort")).setSingleChoiceItems(new String[]{host.t("Name"),host.t("Newest first"),host.t("Largest first")},sort,(d,w)->{sort=w;d.dismiss();render();}).setNegativeButton(android.R.string.cancel,null).show());
        tool(toolbar,host.t("View"),()->{tiles=!tiles;host.getPreferences(0).edit().putBoolean("file_grid",tiles).apply();render();});addView(toolbar);
        EditText search=new EditText(host);search.setSingleLine(true);search.setTextColor(-1);search.setHintTextColor(0xffa5b3cc);search.setTextSize(15);search.setHint(host.t("Filter this folder…"));search.setPadding(host.dp(14),host.dp(6),host.dp(14),host.dp(6));search.setBackground(host.shape(host.SURFACE,0xff293650));addView(search,new LayoutParams(-1,host.dp(44)));
        summary=host.label("",12);summary.setTextColor(0xffa5b3cc);addView(summary);
        grid=new GridView(host);grid.setVerticalSpacing(host.dp(8));grid.setHorizontalSpacing(host.dp(10));grid.setStretchMode(GridView.STRETCH_COLUMN_WIDTH);grid.setClipToPadding(false);grid.setPadding(host.dp(3),host.dp(3),host.dp(3),host.dp(3));
        addView(grid,new LayoutParams(-1,host.dp(host.television?300:390)));
        commands=new LinearLayout(host);addView(commands);render();
        search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int c,int f){}public void onTextChanged(CharSequence s,int a,int b,int c){query=s.toString();render();}public void afterTextChanged(Editable e){}});
        grid.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){public void onItemSelected(AdapterView<?> parent,View view,int index,long id){if(index>=0&&index<visible.size())host.browserSelection=visible.get(index).optString("name");}public void onNothingSelected(AdapterView<?> parent){}});
        if(host.television)grid.post(()->grid.requestFocus());
        grid.setOnItemClickListener((a,v,index,id)->{JSONObject item=visible.get(index);if(!selection.isEmpty())toggle(item);else open(item);});
        grid.setOnItemLongClickListener((a,v,index,id)->{menu(visible.get(index));return true;});
        grid.setOnKeyListener((v,key,event)->{if(event.getAction()==KeyEvent.ACTION_DOWN&&(key==KeyEvent.KEYCODE_MENU||key==KeyEvent.KEYCODE_BUTTON_Y)){int index=grid.getSelectedItemPosition();if(index>=0&&index<visible.size())menu(visible.get(index));return true;}return false;});
        TextView hint=host.label(host.t(host.television?"OK opens · Hold OK for actions · Back goes up":"Hold an item for actions or selection"),12);hint.setTextColor(0xffa5b3cc);addView(hint);
    }
    String deviceName(){JSONArray peers=host.state.optJSONArray("peers");if(peers!=null)for(int i=0;i<peers.length();i++)if(peers.optJSONObject(i).optString("id").equals(host.peer))return peers.optJSONObject(i).optString("name");return host.t("Device");}
    void tool(LinearLayout row,String title,Runnable task){Button button=host.button(title,task);button.setTextSize(13);button.setMinHeight(host.dp(40));LayoutParams p=new LayoutParams(0,host.dp(44),1);p.setMargins(0,0,host.dp(5),host.dp(8));row.addView(button,p);}
    void render(){
        visible.clear();for(JSONObject item:all)if(item.optString("name").toLowerCase(Locale.ROOT).contains(query.toLowerCase(Locale.ROOT)))visible.add(item);
        visible.sort((a,b)->{int group=Boolean.compare(b.optBoolean("directory"),a.optBoolean("directory"));if(group!=0)return group;int value=sort==1?Long.compare(b.optLong("modified"),a.optLong("modified")):sort==2?Long.compare(b.optLong("bytes"),a.optLong("bytes")):0;return value!=0?value:a.optString("name").compareToIgnoreCase(b.optString("name"));});
        grid.setNumColumns(tiles?(host.television?4:2):1);
        grid.setAdapter(new BaseAdapter(){public int getCount(){return visible.size();}public Object getItem(int p){return visible.get(p);}public long getItemId(int p){return p;}public View getView(int p,View old,ViewGroup parent){
            JSONObject item=visible.get(p);boolean picked=selection.contains(item.optString("name"));LinearLayout row=host.column();row.setGravity(tiles?Gravity.CENTER:Gravity.CENTER_VERTICAL);row.setPadding(host.dp(12),host.dp(12),host.dp(12),host.dp(12));row.setMinimumHeight(host.dp(tiles?148:72));
            android.graphics.drawable.StateListDrawable bg=new android.graphics.drawable.StateListDrawable();bg.addState(new int[]{android.R.attr.state_pressed},host.shape(0xff1d3152,host.CYAN));bg.addState(new int[]{},host.shape(picked?0xff1d3152:host.SURFACE,picked?host.CYAN:0xff293650));row.setBackground(bg);
            LinearLayout top=new LinearLayout(host);top.setGravity(Gravity.CENTER_VERTICAL);if(tiles)top.setGravity(Gravity.CENTER);
            View icon=new FileGlyph(host,item.optBoolean("directory"));LayoutParams iconSize=new LayoutParams(host.dp(tiles?58:36),host.dp(tiles?58:36));iconSize.setMargins(0,0,host.dp(tiles?0:12),0);top.addView(icon,iconSize);
            LinearLayout text=host.column();TextView name=host.label((picked?"✓  ":"")+item.optString("name"),host.television?16:15);name.setMaxLines(tiles?3:2);name.setEllipsize(TextUtils.TruncateAt.MIDDLE);name.setTypeface(null,Typeface.BOLD);if(tiles)name.setGravity(Gravity.CENTER);text.addView(name);
            TextView detail=host.label(item.optBoolean("directory")?host.t("Folder"):android.text.format.Formatter.formatShortFileSize(host,item.optLong("bytes")),12);detail.setTextColor(0xffa5b3cc);if(tiles)detail.setGravity(Gravity.CENTER);text.addView(detail);
            if(tiles){row.addView(top);row.addView(text,new LayoutParams(-1,-2));}else{top.addView(text,new LayoutParams(0,-2,1));row.addView(top);}row.setLayoutParams(new AbsListView.LayoutParams(-1,host.dp(tiles?174:86)));return row;
        }});
        grid.setSelector(host.shape(0x00000000,host.CYAN));grid.setDrawSelectorOnTop(true);
        int initial=0;for(int i=0;i<visible.size();i++)if(visible.get(i).optString("name").equals(host.browserSelection))initial=i;grid.setSelection(initial);
        summary.setText(visible.size()+" "+host.t("items")+(selection.isEmpty()?"":" · "+selection.size()+" "+host.t("selected")));commands.removeAllViews();
        if(!selection.isEmpty()){tool(commands,host.t("Copy"),()->destination(false));if(host.peer.isEmpty())tool(commands,host.t("Move"),()->destination(true));tool(commands,host.t("Delete"),this::delete);tool(commands,"×",()->{selection.clear();render();});}
    }
    void open(JSONObject item){host.browserSelection=item.optString("name");if(item.optBoolean("directory")){host.path=host.selectedPath(item);host.browserSelection="";host.browse();}else menu(item);}
    void toggle(JSONObject item){String name=item.optString("name");if(!selection.add(name))selection.remove(name);host.browserSelection=name;render();}
    void menu(JSONObject item){String selected=host.selectedPath(item);ArrayList<String> labels=new ArrayList<>(Arrays.asList(host.t("Open"),host.t("Select"),host.t("Copy"),host.t("Rename"),host.t("Properties"),host.t("Delete")));
        new AlertDialog.Builder(host).setTitle(item.optString("name")).setItems(labels.toArray(new String[0]),(d,w)->{switch(w){case 0:if(item.optBoolean("directory")){host.path=selected;host.browse();}else if(host.peer.isEmpty())host.openLocal(selected);else{selection.clear();selection.add(item.optString("name"));destination(false);}break;case 1:toggle(item);break;case 2:selection.clear();selection.add(item.optString("name"));destination(false);break;case 3:host.editFileName(item,false);break;case 4:properties(item);break;case 5:host.confirmDelete(item);}}).setNegativeButton(android.R.string.cancel,null).show();
    }
    void properties(JSONObject item){String date=item.optLong("modified")>0?android.text.format.DateFormat.format("dd.MM.yyyy HH:mm",new Date(item.optLong("modified")*1000)).toString():"—";TextView details=new TextView(host);details.setTextColor(0xff14233a);details.setTextIsSelectable(true);details.setPadding(host.dp(24),host.dp(16),host.dp(24),host.dp(16));details.setText(host.selectedPath(item)+"\n\n"+host.t("Type")+": "+host.t(item.optBoolean("directory")?"Folder":"File")+"\n"+host.t("Size")+": "+(item.optBoolean("directory")?host.t("Folder size has not been calculated"):android.text.format.Formatter.formatFileSize(host,item.optLong("bytes")))+"\n"+host.t("Modified")+": "+date);new AlertDialog.Builder(host).setTitle(host.t("Properties")).setView(details).setPositiveButton(android.R.string.ok,null).show();}
    JSONArray paths(){JSONArray values=new JSONArray();for(String name:selection)values.put((host.path.equals("/")?"/":host.path+"/")+name);return values;}
    void delete(){if(host.path.equals("/"))return;JSONArray sources=paths();String peer=host.peer;new AlertDialog.Builder(host).setTitle(host.t("Delete permanently?")).setMessage(selection.size()+" "+host.t("selected")+"\n\n"+host.t("This does not use the Trash.")).setNegativeButton(host.t("Keep files"),null).setPositiveButton(host.t("Delete"),(d,w)->host.fileOperation(host.t("Delete"),()->{for(int i=0;i<sources.length();i++)host.core.callAttr("mutate_item",peer,sources.getString(i),"remove","");})).show();}
    void destination(boolean moving){JSONArray sources=paths();String sourcePeer=host.peer;ArrayList<String> names=new ArrayList<>(),ids=new ArrayList<>();names.add(host.t("This device"));ids.add("");JSONArray peers=host.state.optJSONArray("peers");if(!moving&&peers!=null)for(int i=0;i<peers.length();i++){JSONObject p=peers.optJSONObject(i);names.add(p.optString("name"));ids.add(p.optString("id"));}
        new AlertDialog.Builder(host).setTitle(host.t("Choose destination device")).setItems(names.toArray(new String[0]),(d,w)->{String target=ids.get(w);new FolderPicker(host,host.core,host.worker,target,host.t("Choose destination folder"),host::t,folder->new AlertDialog.Builder(host).setTitle(host.t(moving?"Move":"Copy")).setMessage(sources.length()+" "+host.t("items")+"\n"+host.path+"\n↓\n"+names.get(w)+" · "+folder).setNegativeButton(android.R.string.cancel,null).setPositiveButton(host.t(moving?"Move":"Copy"),(box,which)->host.fileOperation(host.t(moving?"Move":"Copy"),()->host.core.callAttr("transfer_items",sourcePeer,sources.toString(),target,folder,moving))).show(),host::error);}).setNegativeButton(android.R.string.cancel,null).show();
    }
}
