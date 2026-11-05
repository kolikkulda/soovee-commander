package cz.soovee.commander;

import android.app.AlertDialog;
import android.content.*;
import android.graphics.*;
import android.media.ThumbnailUtils;
import android.net.Uri;
import android.os.Build;
import android.text.*;
import android.util.LruCache;
import android.util.Size;
import android.view.*;
import android.view.inputmethod.EditorInfo;
import android.widget.*;
import androidx.core.content.FileProvider;
import androidx.recyclerview.widget.*;
import org.json.*;
import java.io.File;
import java.util.*;
import java.util.concurrent.*;

/** The file list for phone and TV: recycled rows or tiles, thumbnails, menus, multi-selection, search. */
final class FileBrowser extends FrameLayout {
    static final Set<String> THUMBS=new HashSet<>(Arrays.asList("jpg","jpeg","png","webp","gif","heic","heif","bmp","mp4","mkv","mov","m4v","3gp","webm"));
    static final Set<String> TEXT=new HashSet<>(Arrays.asList("txt","text","md","markdown","json","csv","tsv","log","xml","yml","yaml","ini","cfg","conf","toml","py","js","ts","html","htm","css","sh","srt","nfo"));
    static final LruCache<String,Bitmap> cache=new LruCache<String,Bitmap>(24*1024*1024){protected int sizeOf(String k,Bitmap v){return v.getByteCount();}};
    static final ExecutorService thumbs=Executors.newFixedThreadPool(2);
    final MainActivity host;final Ui ui;
    final RecyclerView list;final Adapter adapter=new Adapter();
    final ArrayList<JSONObject> all=new ArrayList<>(),visible=new ArrayList<>();
    final LinkedHashSet<String> selection=new LinkedHashSet<>();
    boolean selecting=false,tiles,searchComplete=true;
    String filter="",base=null,query=null;   // base: real local folder (thumbnails, open, share); query: subfolder search
    int sort;
    LinearLayout header;TextView count;EditText search;

    FileBrowser(MainActivity host,JSONArray entries,String base,String query,boolean complete){
        super(host);this.host=host;this.ui=host.ui;this.base=base;this.query=query;this.searchComplete=complete;
        SharedPreferences prefs=host.getSharedPreferences("soovee",0);tiles=prefs.getBoolean("file_grid",false);sort=prefs.getInt("file_sort",0);
        for(int i=0;i<entries.length();i++){JSONObject item=entries.optJSONObject(i);if(item!=null)all.add(item);}
        if(host.path.equals("/")&&host.peer.isEmpty()&&query==null)for(JSONObject item:host.unavailableLocations())all.add(item);
        list=new RecyclerView(host);list.setClipToPadding(false);list.setPadding(0,0,0,ui.dp(24));list.setItemAnimator(null);list.setHasFixedSize(false);
        buildHeader();applyLayout();list.setAdapter(adapter);addView(list,new LayoutParams(-1,-1));refresh();
    }
    void applyLayout(){
        if(!tiles){list.setLayoutManager(new LinearLayoutManager(host));return;}
        int columns=Math.max(2,(int)(getResources().getDisplayMetrics().widthPixels/getResources().getDisplayMetrics().density/(ui.tv?170:124)));
        GridLayoutManager grid=new GridLayoutManager(host,columns);grid.setSpanSizeLookup(new GridLayoutManager.SpanSizeLookup(){public int getSpanSize(int p){return p==0?columns:1;}});list.setLayoutManager(grid);
    }

    // ---------- data ----------
    void refresh(){
        visible.clear();String f=filter.toLowerCase(Locale.ROOT);
        for(JSONObject item:all)if(f.isEmpty()||item.optString("name").toLowerCase(Locale.ROOT).contains(f))visible.add(item);
        visible.sort((a,b)->{int g=Boolean.compare(b.optBoolean("directory"),a.optBoolean("directory"));if(g!=0)return g;
            int v=sort==1?Double.compare(b.optDouble("modified",0),a.optDouble("modified",0)):sort==2?Long.compare(b.optLong("bytes"),a.optLong("bytes")):0;
            return v!=0?v:natural(a.optString("name"),b.optString("name"));});
        HashSet<String> present=new HashSet<>();for(JSONObject item:visible)present.add(item.optString("name"));selection.retainAll(present);
        adapter.notifyDataSetChanged();updateCount();host.updateSelectionBar(this);
    }
    /** "file 2" before "file 10", like Finder and Files. */
    static int natural(String a,String b){
        int i=0,j=0;while(i<a.length()&&j<b.length()){char x=a.charAt(i),y=b.charAt(j);
            if(Character.isDigit(x)&&Character.isDigit(y)){int si=i,sj=j;while(i<a.length()&&Character.isDigit(a.charAt(i)))i++;while(j<b.length()&&Character.isDigit(b.charAt(j)))j++;
                String na=a.substring(si,i).replaceFirst("^0+(?=.)",""),nb=b.substring(sj,j).replaceFirst("^0+(?=.)","");int c=na.length()!=nb.length()?Integer.compare(na.length(),nb.length()):na.compareTo(nb);if(c!=0)return c;}
            else{int c=Character.compare(Character.toLowerCase(x),Character.toLowerCase(y));if(c!=0)return c;i++;j++;}}
        return Integer.compare(a.length()-i,b.length()-j);
    }
    void updateCount(){
        if(count==null)return;int n=visible.size();String items=itemCount(n);
        if(!selection.isEmpty())count.setText(items+" · "+selection.size()+" "+host.t("selected"));
        else if(query!=null)count.setText(items+" · "+host.t(searchComplete?"in all subfolders":"first results only"));
        else if(!filter.isEmpty()&&local()&&!root())count.setText(items+" · "+host.t("Search key searches subfolders too"));
        else count.setText(root()&&local()?host.t("Locations"):items);
    }
    String itemCount(int n){String key=n==1?"item":(n>=2&&n<=4)?"items (2-4)":"items";String word=host.t(key);if(word.equals("items (2-4)"))word="items";return n+" "+word;}   // Czech has three forms
    boolean root(){return host.path.equals("/");}
    boolean local(){return host.peer.isEmpty();}
    String itemPath(JSONObject item){return (root()?"/":host.path+"/")+item.optString("name");}
    File localFile(JSONObject item){return base==null?null:new File(base,item.optString("name"));}
    String extension(String name){int dot=name.lastIndexOf('.');return dot<0?"":name.substring(dot+1).toLowerCase(Locale.ROOT);}
    String symbol(JSONObject item){
        String name=item.optString("name");
        if(item.optBoolean("unavailable"))return "unavailable";
        if(item.optBoolean("directory"))return root()&&local()?(name.equals("Shared")?"phone":"storage"):"folder";
        String e=extension(name);
        if(Arrays.asList("jpg","jpeg","png","webp","gif","heic","heif","bmp").contains(e))return "image";
        if(Arrays.asList("mp4","mkv","mov","avi","m4v","3gp","webm").contains(e))return "movie";
        if(Arrays.asList("mp3","flac","m4a","wav","ogg","aac").contains(e))return "music";
        if(Arrays.asList("zip","rar","7z","tar","gz","tgz","bz2","xz").contains(e))return "archive";
        if(TEXT.contains(e))return "text";
        return "file";
    }
    String detail(JSONObject item){
        if(item.optBoolean("unavailable"))return host.t("Not available now");
        if(root()&&local()){String n=item.optString("name");return host.t(n.equals("Shared")?"Soovee folder on this device":"Device storage");}
        String size=item.optBoolean("directory")?host.t("Folder"):android.text.format.Formatter.formatShortFileSize(host,item.optLong("bytes"));
        double modified=item.optDouble("modified",0);String text=size;
        if(modified>0)text+=" · "+android.text.format.DateUtils.getRelativeTimeSpanString((long)(modified*1000),System.currentTimeMillis(),android.text.format.DateUtils.MINUTE_IN_MILLIS,android.text.format.DateUtils.FORMAT_ABBREV_RELATIVE);
        String name=item.optString("name");int slash=name.lastIndexOf('/');if(slash>0)text=name.substring(0,slash)+" · "+text;
        return text;
    }

    // ---------- header ----------
    void buildHeader(){
        header=ui.column();header.setPadding(ui.dp(2),0,ui.dp(2),ui.dp(10));
        String title;
        if(query!=null){header.addView(ui.backLink(lastName(host.path),()->{host.openFolder(host.path);}));title="„"+query+"“";}
        else if(!root()){String parent=host.path.substring(0,Math.max(0,host.path.lastIndexOf('/')));if(parent.isEmpty())parent="/";String target=parent;
            header.addView(ui.backLink(parent.equals("/")?(local()?host.t("Files"):host.deviceName(host.peer)):lastName(parent),()->host.openFolder(target)));title=lastName(host.path);}
        else title=local()?host.t("Files"):host.deviceName(host.peer);
        header.addView(ui.largeTitle(title));
        if(!root()||!local()){TextView where=ui.text(host.deviceName(host.peer)+" · "+host.path,13,ui.secondary,false);where.setSingleLine(true);where.setEllipsize(TextUtils.TruncateAt.START);where.setPadding(ui.dp(4),0,0,ui.dp(10));header.addView(where);}
        LinearLayout tools=ui.rowLayout();
        LinearLayout field=ui.rowLayout();field.setBackground(ui.round(ui.surface,14));field.setPadding(ui.dp(12),0,ui.dp(6),0);field.addView(ui.icon("search",ui.secondary,20));
        search=new EditText(host);search.setBackground(null);search.setSingleLine(true);search.setTextSize(15);search.setTextColor(ui.text);search.setHintTextColor(ui.tertiary);search.setText(filter);
        search.setHint(host.t(query!=null?"Filter results":"Filter or search"));search.setImeOptions(local()&&!root()&&query==null?EditorInfo.IME_ACTION_SEARCH:EditorInfo.IME_ACTION_DONE);
        search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int b,int c){}public void onTextChanged(CharSequence s,int a,int b,int c){filter=s.toString();refresh();}public void afterTextChanged(Editable e){}});
        search.setOnEditorActionListener((v,action,event)->{if(action==EditorInfo.IME_ACTION_SEARCH&&!filter.isEmpty()){host.hideKeyboard(search);host.deepSearch(filter);return true;}if(action==EditorInfo.IME_ACTION_DONE)host.hideKeyboard(search);return false;});
        field.addView(search,new LinearLayout.LayoutParams(0,ui.dp(46),1));tools.addView(field,new LinearLayout.LayoutParams(0,-2,1));
        tools.addView(toolButton("sort",host.t("Sort"),this::sortMenu));tools.addView(toolButton("more",host.t("More"),this::moreMenu));
        header.addView(tools);
        count=ui.text("",13,ui.secondary,false);count.setPadding(ui.dp(4),ui.dp(10),0,0);header.addView(count);
    }
    String lastName(String path){int slash=path.lastIndexOf('/');return slash<0?path:path.substring(slash+1);}
    View toolButton(String icon,String label,java.util.function.Consumer<View> action){
        ImageButton b=new ImageButton(host);b.setImageDrawable(new Ui.Icon(icon,ui.accent));b.setScaleType(ImageView.ScaleType.FIT_CENTER);b.setPadding(ui.dp(11),ui.dp(11),ui.dp(11),ui.dp(11));
        b.setBackground(ui.pressable(Ui.blend(ui.surface,ui.accent,0.12f),14));b.setContentDescription(label);b.setOnClickListener(action::accept);
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(ui.dp(46),ui.dp(46));p.setMargins(ui.dp(8),0,0,0);b.setLayoutParams(p);return b;
    }
    void sortMenu(View anchor){
        PopupMenu menu=new PopupMenu(host,anchor);String[] names={"Name","Newest first","Largest first"};
        for(int i=0;i<3;i++)menu.getMenu().add(0,i,i,host.t(names[i])).setCheckable(true).setChecked(i==sort);
        menu.getMenu().setGroupCheckable(0,true,true);
        menu.getMenu().add(1,10,10,host.t("List")).setCheckable(true).setChecked(!tiles);menu.getMenu().add(1,11,11,host.t("Grid")).setCheckable(true).setChecked(tiles);menu.getMenu().setGroupCheckable(1,true,true);
        menu.setOnMenuItemClickListener(m->{SharedPreferences.Editor e=host.getSharedPreferences("soovee",0).edit();int id=m.getItemId();
            if(id<3){sort=id;e.putInt("file_sort",id);}else{tiles=id==11;e.putBoolean("file_grid",tiles);applyLayout();}e.apply();refresh();return true;});
        menu.show();
    }
    void moreMenu(View anchor){
        PopupMenu menu=new PopupMenu(host,anchor);Menu m=menu.getMenu();
        if(!root())m.add(0,1,1,host.t("New folder"));
        if(!root()&&local())m.add(0,2,2,host.t("New text file"));
        if(!visible.isEmpty())m.add(0,3,3,host.t("Select"));
        if(!root()&&query==null){boolean fav=host.isFavorite(host.path);m.add(0,4,4,host.t(fav?"Remove from favorites":"Add to favorites"));}
        if(!root()&&local()&&query==null)m.add(0,5,5,host.t("Search subfolders…"));
        if(!ui.tv&&!root())m.add(0,6,6,host.t("Import files…"));
        m.add(0,7,7,host.t("Refresh"));
        menu.setOnMenuItemClickListener(i->{switch(i.getItemId()){
            case 1:host.editName(null,true);break;case 2:host.newTextFile();break;case 3:startSelection();break;
            case 4:host.toggleFavorite(host.path,lastName(host.path));break;case 5:host.askSearch();break;case 6:host.chooseUpload();break;default:host.refreshFiles();}return true;});
        menu.show();
    }

    // ---------- selection ----------
    void startSelection(){selecting=true;adapter.notifyDataSetChanged();updateCount();host.updateSelectionBar(this);}
    void toggle(String name){if(!selection.remove(name))selection.add(name);selecting=true;adapter.notifyDataSetChanged();updateCount();host.updateSelectionBar(this);}
    void endSelection(){selection.clear();selecting=false;adapter.notifyDataSetChanged();updateCount();host.updateSelectionBar(this);}
    void selectAll(boolean on){selection.clear();if(on)for(JSONObject item:visible)if(!item.optBoolean("unavailable"))selection.add(item.optString("name"));selecting=true;adapter.notifyDataSetChanged();updateCount();host.updateSelectionBar(this);}
    ArrayList<JSONObject> selectedItems(){ArrayList<JSONObject> out=new ArrayList<>();for(JSONObject item:visible)if(selection.contains(item.optString("name")))out.add(item);return out;}

    // ---------- interaction ----------
    void clicked(JSONObject item){
        String name=item.optString("name");
        if(item.optBoolean("unavailable")){host.unavailableLocation(name);return;}
        if(selecting){toggle(name);return;}
        if(item.optBoolean("directory")){host.openFolder(itemPath(item));return;}
        host.openItem(this,item);
    }
    void menu(View anchor,JSONObject item){
        String name=item.optString("name");boolean dir=item.optBoolean("directory");
        if(item.optBoolean("unavailable")){host.unavailableLocation(name);return;}
        PopupMenu menu=new PopupMenu(host,anchor,Gravity.END);Menu m=menu.getMenu();
        m.add(0,1,1,host.t("Open"));
        if(local()&&!dir&&TEXT.contains(extension(name))&&base!=null)m.add(0,2,2,host.t("Edit"));
        if(local()&&!dir&&!root())m.add(0,3,3,host.t("Share"));
        m.add(1,4,4,host.t("Select"));
        if(!root())m.add(1,5,5,host.t("Copy to…"));
        if(local()&&!root())m.add(1,6,6,host.t("Move to…"));
        if(local()&&!root())m.add(1,7,7,host.t("Duplicate"));
        if(!root())m.add(1,8,8,host.t("Rename"));
        if(local()&&!root()&&host.isArchive(name)&&!dir)m.add(1,9,9,host.t("Extract here"));
        if(local()&&!root())m.add(1,10,10,host.t("Compress"));
        if(dir&&!root()){boolean fav=host.isFavorite(itemPath(item));m.add(1,11,11,host.t(fav?"Remove from favorites":"Add to favorites"));}
        m.add(2,12,12,host.t("Properties"));
        if(!root())m.add(3,13,13,host.t("Delete"));
        menu.setOnMenuItemClickListener(i->{switch(i.getItemId()){
            case 1:clicked(item);break;case 2:host.editText(localFile(item));break;case 3:host.share(Collections.singletonList(localFile(item)));break;
            case 4:toggle(name);break;case 5:host.chooseDestination(this,Collections.singletonList(item),false);break;case 6:host.chooseDestination(this,Collections.singletonList(item),true);break;
            case 7:host.duplicate(itemPath(item));break;case 8:host.editName(item,false);break;case 9:host.extract(itemPath(item));break;case 10:host.compress(Collections.singletonList(name));break;
            case 11:host.toggleFavorite(itemPath(item),lastName(name));break;case 12:host.properties(item,itemPath(item));break;case 13:host.confirmDelete(Collections.singletonList(item));break;}return true;});
        menu.show();
    }

    // ---------- thumbnails ----------
    void thumbnail(ImageView view,JSONObject item,int px){
        File file=localFile(item);if(file==null||item.optBoolean("directory")||!THUMBS.contains(extension(item.optString("name"))))return;
        String key=file.getPath()+"|"+item.optDouble("modified",0)+"|"+px;Bitmap hit=cache.get(key);view.setTag(key);
        if(hit!=null){view.setImageBitmap(hit);view.setScaleType(ImageView.ScaleType.CENTER_CROP);view.setPadding(0,0,0,0);return;}
        thumbs.execute(()->{Bitmap b=null;try{
            boolean video=Arrays.asList("mp4","mkv","mov","m4v","3gp","webm").contains(extension(file.getName()));
            if(Build.VERSION.SDK_INT>=29)b=video?ThumbnailUtils.createVideoThumbnail(file,new Size(px,px),null):ThumbnailUtils.createImageThumbnail(file,new Size(px,px),null);
            else if(!video){BitmapFactory.Options o=new BitmapFactory.Options();o.inJustDecodeBounds=true;BitmapFactory.decodeFile(file.getPath(),o);int s=1;while(o.outWidth/s>px*2||o.outHeight/s>px*2)s*=2;o=new BitmapFactory.Options();o.inSampleSize=s;b=BitmapFactory.decodeFile(file.getPath(),o);}
        }catch(Exception ignored){}
            if(b==null)return;Bitmap done=b;cache.put(key,done);
            view.post(()->{if(key.equals(view.getTag())){view.setImageBitmap(done);view.setScaleType(ImageView.ScaleType.CENTER_CROP);view.setPadding(0,0,0,0);}});});
    }

    // ---------- adapter ----------
    final class Holder extends RecyclerView.ViewHolder{
        ImageView icon,check;TextView name,detail;ImageButton more;LinearLayout box;
        Holder(View v){super(v);}
    }
    final class Adapter extends RecyclerView.Adapter<Holder>{
        @Override public int getItemCount(){return visible.size()+1;}
        @Override public int getItemViewType(int p){return p==0?0:tiles?2:1;}
        @Override public Holder onCreateViewHolder(ViewGroup parent,int type){
            if(type==0){if(header.getParent()!=null)((ViewGroup)header.getParent()).removeView(header);header.setLayoutParams(new RecyclerView.LayoutParams(-1,-2));return new Holder(header);}
            if(type==1){
                LinearLayout row=ui.rowLayout();row.setMinimumHeight(ui.dp(ui.tv?66:62));row.setPadding(ui.dp(12),ui.dp(6),ui.dp(4),ui.dp(6));
                RecyclerView.LayoutParams lp=new RecyclerView.LayoutParams(-1,-2);lp.setMargins(0,0,0,ui.dp(1));row.setLayoutParams(lp);
                Holder h=new Holder(row);h.box=row;
                h.check=ui.icon("circle",ui.tertiary,24);((LinearLayout.LayoutParams)h.check.getLayoutParams()).setMargins(0,0,ui.dp(10),0);row.addView(h.check);
                h.icon=new ImageView(host);h.icon.setClipToOutline(true);h.icon.setBackground(ui.round(0x00000000,8));LinearLayout.LayoutParams ip=new LinearLayout.LayoutParams(ui.dp(42),ui.dp(42));ip.setMargins(0,0,ui.dp(14),0);row.addView(h.icon,ip);
                LinearLayout texts=ui.column();h.name=ui.text("",ui.tv?17:16,ui.text,false);h.name.setMaxLines(2);h.name.setEllipsize(TextUtils.TruncateAt.MIDDLE);texts.addView(h.name);
                h.detail=ui.text("",13,ui.secondary,false);h.detail.setSingleLine(true);h.detail.setEllipsize(TextUtils.TruncateAt.START);texts.addView(h.detail);row.addView(texts,new LinearLayout.LayoutParams(0,-2,1));
                h.more=ui.moreButton(host.t("More"),null);row.addView(h.more);
                row.setFocusable(true);row.setClickable(true);return h;
            }
            LinearLayout tile=ui.column();tile.setGravity(Gravity.CENTER_HORIZONTAL);tile.setPadding(ui.dp(8),ui.dp(10),ui.dp(8),ui.dp(10));
            RecyclerView.LayoutParams lp=new RecyclerView.LayoutParams(-1,-2);lp.setMargins(ui.dp(4),ui.dp(4),ui.dp(4),ui.dp(4));tile.setLayoutParams(lp);
            Holder h=new Holder(tile);h.box=tile;
            FrameLayout frame=new FrameLayout(host);h.icon=new ImageView(host);h.icon.setClipToOutline(true);h.icon.setBackground(ui.round(0x00000000,10));frame.addView(h.icon,new FrameLayout.LayoutParams(-1,-1));
            h.check=ui.icon("check",ui.accent,22);frame.addView(h.check,new FrameLayout.LayoutParams(ui.dp(22),ui.dp(22),Gravity.TOP|Gravity.END));
            tile.addView(frame,new LinearLayout.LayoutParams(ui.dp(ui.tv?96:76),ui.dp(ui.tv?96:76)));
            h.name=ui.text("",13,ui.text,false);h.name.setMaxLines(2);h.name.setGravity(Gravity.CENTER);h.name.setEllipsize(TextUtils.TruncateAt.MIDDLE);LinearLayout.LayoutParams np=new LinearLayout.LayoutParams(-1,-2);np.setMargins(0,ui.dp(6),0,0);tile.addView(h.name,np);
            h.detail=ui.text("",11,ui.secondary,false);h.detail.setGravity(Gravity.CENTER);h.detail.setSingleLine(true);tile.addView(h.detail,new LinearLayout.LayoutParams(-1,-2));
            tile.setFocusable(true);tile.setClickable(true);return h;
        }
        @Override public void onBindViewHolder(Holder h,int position){
            if(position==0)return;JSONObject item=visible.get(position-1);String name=item.optString("name");boolean picked=selection.contains(name),dir=item.optBoolean("directory");
            boolean listRow=getItemViewType(position)==1;
            h.box.setBackground(ui.pressable(picked?Ui.blend(ui.surface,ui.accent,0.22f):ui.surface,listRow?12:16));
            h.name.setText(name.contains("/")?name.substring(name.lastIndexOf('/')+1):name);h.detail.setText(listRow?detail(item):dir?host.t("Folder"):android.text.format.Formatter.formatShortFileSize(host,item.optLong("bytes")));
            int tint=item.optBoolean("unavailable")?ui.tertiary:dir?ui.accent:ui.secondary;h.icon.setTag(null);h.icon.setImageDrawable(new Ui.Icon(symbol(item),tint));h.icon.setScaleType(ImageView.ScaleType.FIT_CENTER);
            int pad=ui.dp(listRow?5:12);h.icon.setPadding(pad,pad,pad,pad);
            thumbnail(h.icon,item,ui.dp(listRow?84:160));
            if(listRow){h.check.setVisibility(selecting?VISIBLE:GONE);h.check.setImageDrawable(new Ui.Icon(picked?"check":"circle",picked?ui.accent:ui.tertiary));
                h.more.setVisibility(selecting||item.optBoolean("unavailable")?GONE:VISIBLE);h.more.setOnClickListener(v->menu(v,item));}
            else h.check.setVisibility(picked?VISIBLE:GONE);
            h.box.setOnClickListener(v->clicked(item));
            h.box.setOnLongClickListener(v->{if(ui.tv||root()){menu(v,item);}else toggle(name);return true;});
            h.box.setOnKeyListener((v,key,event)->{if(event.getAction()==KeyEvent.ACTION_DOWN&&(key==KeyEvent.KEYCODE_MENU||key==KeyEvent.KEYCODE_BUTTON_Y)){menu(v,item);return true;}return false;});
            h.box.setContentDescription(name+", "+detail(item)+(picked?", "+host.t("selected"):""));
        }
    }
}
