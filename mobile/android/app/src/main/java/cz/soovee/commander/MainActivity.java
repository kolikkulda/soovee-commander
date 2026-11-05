package cz.soovee.commander;

import android.app.*;
import android.content.*;
import android.content.res.Configuration;
import android.database.Cursor;
import android.graphics.*;
import android.net.Uri;
import android.os.*;
import android.provider.OpenableColumns;
import android.text.TextUtils;
import android.view.*;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import androidx.core.content.FileProvider;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;
import org.json.*;
import java.io.*;
import java.nio.charset.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Phone and TV UI. Authorization and filesystem safety stay in the shared Python core. */
public class MainActivity extends androidx.activity.ComponentActivity {
    final androidx.activity.result.ActivityResultLauncher<com.journeyapps.barcodescanner.ScanOptions> scanner=registerForActivityResult(new com.journeyapps.barcodescanner.ScanContract(),result->{
        if(result.getContents()!=null)callState("pair",result.getContents(),"","0","");
    });
    final ExecutorService worker=Executors.newSingleThreadExecutor();
    final Handler timer=new Handler(Looper.getMainLooper());
    final Set<AlertDialog> approvals=new HashSet<>();
    Ui ui;FrameLayout body;LinearLayout tabs,selectionBar,rail;ScrollView scroll;LinearLayout content;
    TextView code,address,expiry;ImageView qr;
    PyObject core;JSONObject state=new JSONObject(),translations=new JSONObject();
    String screen="home",peer="",path="/",lastInvitation="",uploadPeer="",uploadPath="";boolean television,ready=false;
    NetworkDiscovery network;FileBrowser browser;
    final AtomicBoolean snapshotPending=new AtomicBoolean(false);
    Runnable refresh;
    // progress sheet
    Dialog progressSheet;ProgressBar progressBar;TextView progressName,progressBytes,progressPercent,progressSpeed;long progressStarted;boolean progressStopped,operationRunning;String operationTitle="";

    /** Dialogs match the app's light or dark look (the TV is always dark). */
    AlertDialog.Builder dialog(){return new AlertDialog.Builder(this,ui!=null&&ui.dark?android.R.style.Theme_Material_Dialog_Alert:android.R.style.Theme_Material_Light_Dialog_Alert);}
    String t(String source){return translations.optString(source,source);}
    int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}

    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);
        try{if(getResources().getConfiguration().getLocales().get(0).getLanguage().equals("cs")){try(InputStream in=getAssets().open("cs.json")){translations=new JSONObject(new String(readAll(in),StandardCharsets.UTF_8));}}}catch(Exception ignored){}
        television=getIntent().getBooleanExtra("tvMode",(getResources().getConfiguration().uiMode&Configuration.UI_MODE_TYPE_MASK)==Configuration.UI_MODE_TYPE_TELEVISION);
        if(television)getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN|WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        buildShell();
        worker.execute(()->{try{
            if(!Python.isStarted())Python.start(new AndroidPlatform(this));core=Python.getInstance().getModule("soovee_mobile");
            core.callAttr("start",new File(getFilesDir(),"transfer-state").toString(),new File(getFilesDir(),"Shared").toString(),Build.MODEL,television?"tv":"phone",this);
            String initial=storageState();
            android.util.Log.i("SooveeCommander","Transfers ready · "+core.callAttr("runtime_check").toString());
            runOnUiThread(()->{ready=true;update(initial);showHome();if(getIntent().getDataString()!=null)callState("pair",getIntent().getDataString(),"","0","");});
        }catch(Exception e){error(e);}});
        refresh=new Runnable(){public void run(){if(ready&&snapshotPending.compareAndSet(false,true))worker.execute(()->{try{String value=core.callAttr("snapshot").toString();runOnUiThread(()->update(value));}catch(Exception e){error(e);}finally{snapshotPending.set(false);}});timer.postDelayed(this,3000);}};timer.postDelayed(refresh,3000);
    }
    static byte[] readAll(InputStream in)throws IOException{ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))!=-1)bytes.write(buffer,0,n);return bytes.toByteArray();}

    // ---------- shell: bottom tabs on phones, navigation rail on TV ----------
    void buildShell(){
        ui=new Ui(this);
        getWindow().setStatusBarColor(ui.bg);getWindow().setNavigationBarColor(ui.bg);
        if(Build.VERSION.SDK_INT>=26&&!ui.dark)getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        LinearLayout root=ui.column();root.setFitsSystemWindows(true);root.setBackgroundColor(ui.bg);
        body=new FrameLayout(this);
        String[] names={"Overview","Files","Devices","Transfers"};String[] icons={"home","folder","devices","swap"};
        Runnable[] tasks={this::showHome,()->{peer="";openFolder("/");},this::showNearby,this::showTransfers};
        if(television){
            LinearLayout frame=ui.rowLayout();frame.setGravity(Gravity.TOP);rail=ui.column();rail.setPadding(dp(16),dp(24),dp(8),dp(16));
            ImageView logo=new ImageView(this);logo.setImageResource(R.drawable.soovee_icon);logo.setClipToOutline(true);logo.setBackground(ui.round(0,10));rail.addView(logo,new LinearLayout.LayoutParams(dp(44),dp(44)));
            View space=new View(this);rail.addView(space,new LinearLayout.LayoutParams(1,dp(18)));
            for(int i=0;i<4;i++)rail.addView(railItem(icons[i],t(names[i]),tasks[i]));
            rail.addView(railItem("settings",t("Settings"),this::showSettings));
            frame.addView(rail,new LinearLayout.LayoutParams(dp(196),-1));frame.addView(body,new LinearLayout.LayoutParams(0,-1,1));root.addView(frame,new LinearLayout.LayoutParams(-1,-1));
        }else{
            root.addView(body,new LinearLayout.LayoutParams(-1,0,1));
            tabs=ui.rowLayout();tabs.setBackgroundColor(ui.bg);tabs.setPadding(0,dp(4),0,dp(2));
            View line=new View(this);line.setBackgroundColor(ui.separator);root.addView(line,new LinearLayout.LayoutParams(-1,1));
            for(int i=0;i<4;i++){LinearLayout tab=ui.column();tab.setGravity(Gravity.CENTER);tab.setPadding(0,dp(6),0,dp(6));tab.addView(ui.icon(icons[i],ui.secondary,24));TextView label=ui.text(t(names[i]),11.5f,ui.secondary,true);label.setPadding(0,dp(2),0,0);label.setGravity(Gravity.CENTER);label.setSingleLine(true);tab.addView(label,new LinearLayout.LayoutParams(-2,-2));
                tab.setBackground(ui.pressable(0x00000000,14));tab.setClickable(true);tab.setFocusable(true);Runnable task=tasks[i];tab.setOnClickListener(v->task.run());tab.setContentDescription(t(names[i]));tabs.addView(tab,new LinearLayout.LayoutParams(0,-2,1));}
            root.addView(tabs);
            selectionBar=ui.rowLayout();selectionBar.setBackgroundColor(ui.bg);selectionBar.setVisibility(View.GONE);root.addView(selectionBar);
        }
        setContentView(root);
    }
    View railItem(String icon,String label,Runnable task){
        LinearLayout item=ui.rowLayout();item.setPadding(dp(14),dp(10),dp(14),dp(10));item.addView(ui.icon(icon,ui.secondary,24));TextView text=ui.text(label,16,ui.text,true);text.setPadding(dp(14),0,0,0);item.addView(text);
        item.setBackground(ui.pressable(0x00000000,14));item.setFocusable(true);item.setClickable(true);item.setOnClickListener(v->{fromRail=true;task.run();});
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,dp(3),0,dp(3));item.setLayoutParams(p);return item;
    }
    void markTab(int index){currentTab=index<0?4:index;
        if(tabs!=null)for(int i=0;i<tabs.getChildCount();i++){LinearLayout tab=(LinearLayout)tabs.getChildAt(i);int color=i==index?ui.accent:ui.secondary;((ImageView)tab.getChildAt(0)).setImageDrawable(new Ui.Icon(new String[]{"home","folder","devices","swap"}[i],color));((TextView)tab.getChildAt(1)).setTextColor(color);}
        if(rail!=null)for(int i=2;i<rail.getChildCount();i++){LinearLayout item=(LinearLayout)rail.getChildAt(i);int color=i-2==index?ui.accent:ui.secondary;((ImageView)item.getChildAt(0)).setImageDrawable(new Ui.Icon(new String[]{"home","folder","devices","swap","settings"}[i-2],color));}
    }
    /** A scrolling page of sections; returns its column. */
    LinearLayout page(String name,int tab){
        screen=name;browser=null;markTab(tab);updateSelectionBar(null);body.removeAllViews();
        scroll=new ScrollView(this);scroll.setClipToPadding(false);content=ui.column();content.setPadding(dp(television?24:16),dp(television?24:14),dp(television?28:16),dp(28));scroll.addView(content);body.addView(scroll);return content;
    }
    /** TV: Right from the rail enters the page, Left from the page's left edge returns to the rail. */
    @Override public boolean dispatchKeyEvent(KeyEvent event){
        if(television&&event.getAction()==KeyEvent.ACTION_DOWN&&rail!=null){View focused=getCurrentFocus();
            if(event.getKeyCode()==KeyEvent.KEYCODE_DPAD_RIGHT&&focused!=null&&focused.getParent()==rail){View target=firstFocusable(body);if(target!=null){target.requestFocus();return true;}}
            if(event.getKeyCode()==KeyEvent.KEYCODE_DPAD_LEFT&&focused!=null&&isInside(focused,body)&&focused.focusSearch(View.FOCUS_LEFT)==null){View item=rail.getChildAt(Math.max(2,Math.min(rail.getChildCount()-1,2+currentTab)));item.requestFocus();return true;}}
        return super.dispatchKeyEvent(event);
    }
    int currentTab=0;boolean fromRail=false;   // a page opened from the rail keeps the focus there
    boolean isInside(View v,ViewGroup parent){for(android.view.ViewParent p=v.getParent();p!=null;p=p.getParent())if(p==parent)return true;return false;}
    View firstFocusable(ViewGroup group){
        if(browser!=null&&browser.list.getChildCount()>1){View row=browser.list.getChildAt(1);if(row!=null&&row.isFocusable())return row;}
        ArrayList<View> found=new ArrayList<>();group.addFocusables(found,View.FOCUS_FORWARD);for(View v:found)if(!(v instanceof EditText))return v;return found.isEmpty()?null:found.get(0);
    }
    void hideKeyboard(View v){InputMethodManager m=(InputMethodManager)getSystemService(INPUT_METHOD_SERVICE);if(m!=null)m.hideSoftInputFromWindow(v.getWindowToken(),0);}

    // ---------- state ----------
    void update(String value){if(isFinishing())return;try{
        state=new JSONObject(value);
        if(ready&&!state.optString("id").isEmpty()&&(network==null||!network.name.equals(state.optString("name"))||network.port!=state.optInt("port"))){
            if(network!=null)network.close();network=new NetworkDiscovery(this,state.optString("id"),state.optString("name"),state.optInt("port"),television?"tv":"phone",()->runOnUiThread(()->{if(screen.equals("nearby"))showNearby();}));
        }
        if(!screen.equals("pair")||code==null)return;
        String pin=state.optString("code");code.setText(pin.isEmpty()?t("Generate a new code"):pin.substring(0,4)+" "+pin.substring(4));
        address.setText(state.optString("name")+" · "+state.optString("address")+":"+state.optInt("port"));expiry.setText(t("Code valid for")+" "+state.optInt("expires")+" s");
        JSONArray matrix=state.optJSONArray("qr");if(matrix==null){qr.setImageDrawable(null);lastInvitation="";return;}
        if(state.optString("invitation").equals(lastInvitation))return;lastInvitation=state.optString("invitation");
        int n=matrix.length(),scale=8;Bitmap image=Bitmap.createBitmap(n*scale,n*scale,Bitmap.Config.ARGB_8888);Canvas canvas=new Canvas(image);canvas.drawColor(-1);Paint paint=new Paint();paint.setColor(0xff000000);
        for(int y=0;y<n;y++)for(int x=0;x<n;x++)if(matrix.getJSONArray(y).getBoolean(x))canvas.drawRect(x*scale,y*scale,(x+1)*scale,(y+1)*scale,paint);qr.setImageBitmap(image);
    }catch(Exception e){error(e);}}
    String deviceName(String id){if(id==null||id.isEmpty())return t("This device");JSONArray peers=state.optJSONArray("peers");if(peers!=null)for(int i=0;i<peers.length();i++)if(peers.optJSONObject(i).optString("id").equals(id))return peers.optJSONObject(i).optString("name");return t("Device");}
    boolean paired(String identity){JSONArray values=state.optJSONArray("peers");if(values!=null)for(int i=0;i<values.length();i++)if(values.optJSONObject(i).optString("id").equals(identity))return true;return false;}
    NetworkDiscovery.Device nearby(String identity){if(network!=null)for(NetworkDiscovery.Device d:network.snapshot())if(d.id.equals(identity))return d;return null;}
    String kindIcon(String kind){return "tv".equals(kind)?"tv":"phone".equals(kind)?"phone":"computer";}

    // ---------- Overview ----------
    void showHome(){LinearLayout c=page("home",0);peer="";path="/";
        LinearLayout titleRow=ui.rowLayout();titleRow.addView(ui.largeTitle(t("Overview")),new LinearLayout.LayoutParams(0,-2,1));
        if(!television){ImageButton gear=new ImageButton(this);gear.setImageDrawable(new Ui.Icon("settings",ui.accent));gear.setBackground(ui.pressable(ui.surface,22));gear.setPadding(dp(10),dp(10),dp(10),dp(10));gear.setScaleType(ImageView.ScaleType.FIT_CENTER);gear.setContentDescription(t("Settings"));gear.setOnClickListener(v->showSettings());titleRow.addView(gear,new LinearLayout.LayoutParams(dp(44),dp(44)));}
        c.addView(titleRow);
        ArrayList<View> locations=new ArrayList<>();JSONArray volumes=state.optJSONArray("storage");
        if(volumes!=null)for(int i=0;i<volumes.length();i++){JSONObject v=volumes.optJSONObject(i);String name=v.optString("name");long total=v.optLong("total"),free=v.optLong("free");
            String cap=total>0?android.text.format.Formatter.formatShortFileSize(this,free)+" "+t("free of")+" "+android.text.format.Formatter.formatShortFileSize(this,total):"";
            locations.add(ui.row(name.equals("Shared")?"phone":"storage",name.equals("Shared")?0xff0a84ff:0xff5e5ce6,t(name),cap,null,true,()->{peer="";openFolder("/"+name);}));}
        if(!state.optBoolean("storageSharing"))locations.add(ui.row("add",0xff34c759,t("Allow access to device storage…"),t("Internal storage, SD cards and USB drives"),null,true,this::allowStorage));
        c.addView(ui.section(t("Locations"),locations,t("Android protects other apps’ private data. Internal shared storage and supported USB drives can be made available after permission is granted.")));
        ArrayList<View> favorites=new ArrayList<>();for(JSONObject place:places("favorites"))favorites.add(ui.row("star",0xffffcc00,place.optString("name"),placeDetail(place),null,true,()->openPlace(place)));
        if(!favorites.isEmpty())c.addView(ui.section(t("Favorites"),favorites,null));
        ArrayList<View> recent=new ArrayList<>();int n=0;for(JSONObject place:places("recentFolders")){if(n++>=5)break;recent.add(ui.row("history",0xff8e8e93,place.optString("name"),placeDetail(place),null,true,()->openPlace(place)));}
        if(!recent.isEmpty())c.addView(ui.section(t("Recent"),recent,null));
        ArrayList<View> devices=new ArrayList<>();JSONArray peers=state.optJSONArray("peers");
        if(peers!=null)for(int i=0;i<peers.length();i++){JSONObject p=peers.optJSONObject(i);NetworkDiscovery.Device near=nearby(p.optString("id"));
            devices.add(ui.row(kindIcon(near==null?"":near.kind),near!=null?0xff34c759:0xff8e8e93,p.optString("name"),t(near!=null?"On this network":"Not found on this network"),null,true,()->openDevice(p.optString("id"))));}
        devices.add(ui.row("qr",ui.accent,t("Find a device or scan QR"),null,null,true,this::showNearby));
        c.addView(ui.section(t("Devices"),devices,null));
        ArrayList<View> more=new ArrayList<>();
        if(!television)more.add(ui.row("download",0xffff9500,t("Import files…"),t("Copy files into Soovee with the system picker"),null,true,()->{uploadPeer="";uploadPath="";chooseUpload();}));
        more.add(ui.row("settings",0xff8e8e93,t("Settings"),null,null,true,this::showSettings));
        c.addView(ui.section(null,more,null));
    }
    void openPlace(JSONObject place){peer=place.optString("peer");if(!peer.isEmpty()&&!paired(peer)){peer="";error(new Exception(t("This device is no longer paired.")));return;}openFolder(place.optString("path","/"));}
    String placeDetail(JSONObject place){String p=place.optString("path");int s=p.lastIndexOf('/');return deviceName(place.optString("peer"))+" · "+(s<=0?"/":p.substring(0,s));}
    List<JSONObject> places(String key){ArrayList<JSONObject> out=new ArrayList<>();try{JSONArray a=new JSONArray(getSharedPreferences("soovee",0).getString(key,"[]"));for(int i=0;i<a.length();i++)out.add(a.getJSONObject(i));}catch(Exception ignored){}return out;}
    void savePlaces(String key,List<JSONObject> values){JSONArray a=new JSONArray();for(JSONObject v:values)a.put(v);getSharedPreferences("soovee",0).edit().putString(key,a.toString()).apply();}
    boolean isFavorite(String p){for(JSONObject place:places("favorites"))if(place.optString("path").equals(p)&&place.optString("peer").equals(peer))return true;return false;}
    void toggleFavorite(String p,String name){List<JSONObject> list=places("favorites");boolean removed=list.removeIf(x->x.optString("path").equals(p)&&x.optString("peer").equals(peer));
        if(!removed)try{list.add(new JSONObject().put("peer",peer).put("path",p).put("name",name));}catch(JSONException ignored){}savePlaces("favorites",list);toast(t(removed?"Removed from favorites":"Added to favorites"));}
    void rememberFolder(String p){if(p.equals("/"))return;List<JSONObject> list=places("recentFolders");list.removeIf(x->x.optString("path").equals(p)&&x.optString("peer").equals(peer));
        try{list.add(0,new JSONObject().put("peer",peer).put("path",p).put("name",p.substring(p.lastIndexOf('/')+1)));}catch(JSONException ignored){}while(list.size()>10)list.remove(list.size()-1);savePlaces("recentFolders",list);}

    // ---------- Files ----------
    String searchQuery=null;
    void openFolder(String p){path=p;searchQuery=null;refreshFiles();}
    void refreshFiles(){
        if(searchQuery!=null){deepSearch(searchQuery);return;}
        screen="files";markTab(1);body.removeAllViews();ProgressBar spinner=new ProgressBar(this);body.addView(spinner,new FrameLayout.LayoutParams(dp(48),dp(48),Gravity.CENTER));browser=null;updateSelectionBar(null);
        String requestedPeer=peer,requestedPath=path;
        worker.execute(()->{try{
            JSONArray entries=new JSONArray(requestedPeer.isEmpty()?core.callAttr("browse_local_path",requestedPath).toString():core.callAttr("browse",requestedPeer,requestedPath).toString());
            String base=requestedPeer.isEmpty()&&!requestedPath.equals("/")?core.callAttr("local_file",requestedPath).toString():null;
            runOnUiThread(()->{if(isFinishing()||!screen.equals("files")||!peer.equals(requestedPeer)||!path.equals(requestedPath))return;rememberFolder(requestedPath);showBrowser(new FileBrowser(this,entries,base,null,true));});
        }catch(Exception e){runOnUiThread(()->{if(screen.equals("files")&&!requestedPeer.isEmpty()&&requestedPath.equals("/"))showConnection(requestedPeer,"unavailable",e.getMessage());else if(screen.equals("files")){path="/";if(requestedPath.equals("/"))showHome();else refreshFiles();}});error(e);}});
    }
    void showBrowser(FileBrowser view){body.removeAllViews();FrameLayout.LayoutParams p=new FrameLayout.LayoutParams(-1,-1);int side=dp(television?24:12);view.setPadding(side,dp(television?20:8),side,0);body.addView(view,p);browser=view;updateSelectionBar(view);
        boolean keepRail=fromRail;fromRail=false;
        if(television&&!keepRail)view.list.postDelayed(()->{View first=firstFocusable(view);if(first!=null)first.requestFocus();},250);}
    void askSearch(){EditText field=new EditText(this);field.setHint(t("Part of a file name"));field.setSingleLine(true);
        dialog().setTitle(t("Search subfolders…")).setMessage(path).setView(padded(field)).setNegativeButton(t("Cancel"),null).setPositiveButton(t("Search"),(d,w)->{if(field.length()>0)deepSearch(field.getText().toString());}).show();}
    void deepSearch(String query){searchQuery=query;screen="files";body.removeAllViews();body.addView(new ProgressBar(this),new FrameLayout.LayoutParams(dp(48),dp(48),Gravity.CENTER));String requested=path;
        worker.execute(()->{try{JSONObject value=new JSONObject(core.callAttr("search_local",requested,query).toString());String base=core.callAttr("local_file",requested).toString();
            runOnUiThread(()->{if(!screen.equals("files")||!path.equals(requested)||!query.equals(searchQuery))return;showBrowser(new FileBrowser(this,value.optJSONArray("results"),base,query,value.optBoolean("complete")));});}catch(Exception e){searchQuery=null;error(e);}});}
    List<JSONObject> unavailableLocations(){return new ArrayList<>();}
    void unavailableLocation(String name){dialog().setTitle(name).setMessage(t("This location is not available now.")).setPositiveButton(android.R.string.ok,null).show();}
    boolean isArchive(String name){String n=name.toLowerCase(Locale.ROOT);for(String s:new String[]{".zip",".tar",".tgz",".tar.gz",".tar.bz2",".tar.xz"})if(n.endsWith(s))return true;return false;}
    View padded(View v){FrameLayout f=new FrameLayout(this);f.setPadding(dp(22),dp(8),dp(22),0);f.addView(v);return f;}

    /** Selection bar replaces the tabs while items are chosen. */
    void updateSelectionBar(FileBrowser b){
        if(selectionBar==null)return;boolean active=b!=null&&b==browser&&(b.selecting||!b.selection.isEmpty());
        selectionBar.setVisibility(active?View.VISIBLE:View.GONE);tabs.setVisibility(active?View.GONE:View.VISIBLE);selectionBar.removeAllViews();if(!active)return;
        boolean some=!b.selection.isEmpty(),local=peer.isEmpty(),root=path.equals("/"),all=b.selection.size()==b.visible.size();
        barButton(all?"circle":"check",t(all?"Deselect all":"Select all"),ui.accent,true,()->b.selectAll(!all));
        barButton("copy",t("Copy"),ui.accent,some&&!root,()->chooseDestination(b,b.selectedItems(),false));
        if(local&&!root)barButton("folder",t("Move"),ui.accent,some,()->chooseDestination(b,b.selectedItems(),true));
        if(local&&!root&&b.query==null)barButton("archive",t("Compress"),ui.accent,some,()->compress(new ArrayList<>(b.selection)));
        if(local&&!root){ArrayList<File> files=new ArrayList<>();for(JSONObject item:b.selectedItems())if(!item.optBoolean("directory")&&b.localFile(item)!=null)files.add(b.localFile(item));barButton("share",t("Share"),ui.accent,!files.isEmpty(),()->share(files));}
        if(!root)barButton("delete",t("Delete"),ui.danger,some,()->confirmDelete(b.selectedItems()));
        barButton("close",t("Done"),ui.secondary,true,b::endSelection);
    }
    void barButton(String icon,String label,int color,boolean enabled,Runnable action){
        LinearLayout item=ui.column();item.setGravity(Gravity.CENTER);item.setPadding(0,dp(8),0,dp(8));int c=enabled?color:ui.tertiary;item.addView(ui.icon(icon,c,22));TextView l=ui.text(label,11,c,true);l.setSingleLine(true);l.setPadding(0,dp(3),0,0);item.addView(l,new LinearLayout.LayoutParams(-2,-2));
        item.setEnabled(enabled);item.setClickable(enabled);item.setFocusable(enabled);item.setBackground(ui.pressable(0x00000000,12));item.setOnClickListener(v->action.run());item.setContentDescription(label);
        selectionBar.addView(item,new LinearLayout.LayoutParams(0,-2,1));
    }

    // ---------- file actions ----------
    void openItem(FileBrowser b,JSONObject item){
        File file=b.localFile(item);
        if(file!=null){if(FileBrowser.TEXT.contains(b.extension(file.getName()))&&file.length()<1024*1024){openFile(file);return;}openFile(file);return;}
        String source=b.itemPath(item),from=peer;Toast.makeText(this,t("Downloading for preview…"),Toast.LENGTH_SHORT).show();
        worker.execute(()->{try{File copy=new File(core.callAttr("preview_copy",from,source).toString());runOnUiThread(()->openFile(copy));}catch(Exception e){error(e);}});
    }
    void openFile(File file){try{Uri uri=FileProvider.getUriForFile(this,getPackageName()+".files",file);String type=android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(android.webkit.MimeTypeMap.getFileExtensionFromUrl(Uri.encode(file.getName())).toLowerCase(Locale.ROOT));
        if(type==null&&FileBrowser.TEXT.contains(file.getName().substring(file.getName().lastIndexOf('.')+1).toLowerCase(Locale.ROOT)))type="text/plain";
        Intent view=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,type==null?"*/*":type).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try{startActivity(Intent.createChooser(view,file.getName()));}catch(ActivityNotFoundException none){if(FileBrowser.TEXT.contains(file.getName().substring(file.getName().lastIndexOf('.')+1).toLowerCase(Locale.ROOT)))editText(file);else error(new Exception(t("No app on this device can open this file.")));}
    }catch(Exception e){error(e);}}
    void share(List<File> files){try{ArrayList<Uri> uris=new ArrayList<>();for(File f:files)uris.add(FileProvider.getUriForFile(this,getPackageName()+".files",f));if(uris.isEmpty())return;
        Intent send=uris.size()==1?new Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM,uris.get(0)):new Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM,uris);
        send.setType("*/*").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);startActivity(Intent.createChooser(send,t("Share")));}catch(Exception e){error(e);}}
    /** Plain-text editor: keeps UTF-8 or the older Czech Windows encoding, saves atomically. */
    void editText(File file){if(file==null)return;worker.execute(()->{try{
        if(file.length()>4*1024*1024)throw new Exception(t("This file is too large to edit here."));
        byte[] data;try(InputStream in=new FileInputStream(file)){data=readAll(in);}
        Charset charset=StandardCharsets.UTF_8;String text;
        try{text=StandardCharsets.UTF_8.newDecoder().decode(java.nio.ByteBuffer.wrap(data)).toString();}catch(CharacterCodingException bad){charset=Charset.forName("windows-1250");text=new String(data,charset);}
        Charset used=charset;String original=text;
        runOnUiThread(()->{Dialog editor=new Dialog(this,android.R.style.Theme_DeviceDefault_NoActionBar);LinearLayout box=ui.column();box.setBackgroundColor(ui.bg);box.setFitsSystemWindows(true);
            LinearLayout bar=ui.rowLayout();bar.setPadding(dp(8),dp(8),dp(8),dp(8));EditText field=new EditText(this);
            Button cancel=ui.pill(t("Cancel"),ui.surface,ui.text,()->{if(field.getText().toString().equals(original))editor.dismiss();else dialog().setTitle(t("Discard changes?")).setNegativeButton(t("Keep editing"),null).setPositiveButton(t("Discard"),(d,w)->editor.dismiss()).show();});
            TextView title=ui.text(file.getName(),16,ui.text,true);title.setGravity(Gravity.CENTER);title.setSingleLine(true);title.setEllipsize(TextUtils.TruncateAt.MIDDLE);
            Button save=ui.pill(t("Save"),ui.accent,ui.onAccent,()->worker.execute(()->{try{File temp=new File(file.getParentFile(),"."+file.getName()+".soovee-save");try(OutputStream out=new FileOutputStream(temp)){out.write(field.getText().toString().getBytes(used));}
                if(!temp.renameTo(file)){temp.delete();throw new IOException(t("Could not save the file."));}runOnUiThread(()->{editor.dismiss();refreshFiles();});}catch(Exception e){error(e);}}));
            bar.addView(cancel);bar.addView(title,new LinearLayout.LayoutParams(0,-2,1));bar.addView(save);box.addView(bar);
            field.setText(original);field.setTextColor(ui.text);field.setBackground(null);field.setGravity(Gravity.TOP);field.setTypeface(Typeface.MONOSPACE);field.setTextSize(15);field.setPadding(dp(16),dp(8),dp(16),dp(16));
            ScrollView sv=new ScrollView(this);sv.setFillViewport(true);sv.addView(field);box.addView(sv,new LinearLayout.LayoutParams(-1,0,1));editor.setContentView(box);editor.show();});
    }catch(Exception e){error(e);}});}
    void newTextFile(){EditText name=new EditText(this);name.setSingleLine(true);name.setText(t("New text file")+".txt");name.setSelection(0,name.getText().length()-4);
        dialog().setTitle(t("New text file")).setView(padded(name)).setNegativeButton(t("Cancel"),null).setPositiveButton(t("Create"),(d,w)->{String value=name.getText().toString().trim();String folder=path;
            worker.execute(()->{try{core.callAttr("mutate_item","",folder,"newfile",value);String base=core.callAttr("local_file",folder).toString();runOnUiThread(()->{refreshFiles();editText(new File(base,value));});}catch(Exception e){error(e);}});}).show();}
    void editName(JSONObject item,boolean create){if(path.equals("/")){error(new Exception(t("Choose a storage folder first.")));return;}String selected=create?path:(path+"/"+item.optString("name")),from=peer;
        EditText name=new EditText(this);name.setSingleLine(true);name.setText(create?"":item.optString("name"));name.selectAll();
        AlertDialog dialog=dialog().setTitle(t(create?"New folder":"Rename")).setView(padded(name)).setNegativeButton(t("Cancel"),null).setPositiveButton(t(create?"Create":"Rename"),null).create();
        dialog.setOnShowListener(v->dialog.getButton(-1).setOnClickListener(button->{String value=name.getText().toString();if(value.trim().isEmpty()||value.contains("/")||value.contains("\\")||value.equals(".")||value.equals("..")){name.setError(t("Enter a valid name."));return;}dialog.dismiss();
            worker.execute(()->{try{core.callAttr("mutate_item",from,selected,create?"mkdir":"rename",value);runOnUiThread(this::refreshFiles);}catch(Exception e){error(e);}});}));dialog.show();}
    void confirmDelete(List<JSONObject> items){if(path.equals("/")||items.isEmpty())return;ArrayList<String> paths=new ArrayList<>();for(JSONObject i:items)paths.add(path+"/"+i.optString("name"));String from=peer;
        String what=items.size()==1?items.get(0).optString("name"):items.size()+" "+t("selected");
        AlertDialog dialog=dialog().setTitle(t("Delete permanently?")).setMessage(what+"\n\n"+t("This does not use the Trash.")).setNegativeButton(t("Keep files"),null)
            .setPositiveButton(t("Delete"),(d,w)->worker.execute(()->{try{for(String p:paths)core.callAttr("mutate_item",from,p,"remove","");runOnUiThread(this::refreshFiles);}catch(Exception e){runOnUiThread(this::refreshFiles);error(e);}})).create();
        dialog.setOnShowListener(v->{dialog.getButton(-1).setTextColor(ui.danger);dialog.getButton(-2).requestFocus();});dialog.show();}
    void properties(JSONObject item,String selected){String date=item.optDouble("modified",0)>0?android.text.format.DateFormat.getMediumDateFormat(this).format(new Date((long)(item.optDouble("modified")*1000)))+" "+android.text.format.DateFormat.getTimeFormat(this).format(new Date((long)(item.optDouble("modified")*1000))):"—";
        dialog().setTitle(item.optString("name")).setMessage(selected+"\n\n"+t("Size")+": "+(item.optBoolean("directory")?t("Folder size has not been calculated"):android.text.format.Formatter.formatFileSize(this,item.optLong("bytes")))+"\n"+t("Modified")+": "+date).setPositiveButton(android.R.string.ok,null).show();}
    void chooseDestination(FileBrowser b,List<JSONObject> items,boolean moving){if(items.isEmpty())return;JSONArray sources=new JSONArray();for(JSONObject i:items)sources.put(b.itemPath(i));String from=peer;
        ArrayList<String> names=new ArrayList<>(),ids=new ArrayList<>();names.add(t("This device"));ids.add("");JSONArray peers=state.optJSONArray("peers");if(!moving&&peers!=null)for(int i=0;i<peers.length();i++){names.add(peers.optJSONObject(i).optString("name"));ids.add(peers.optJSONObject(i).optString("id"));}
        Runnable[] pick=new Runnable[1];
        java.util.function.IntConsumer chosenDevice=w->new FolderPicker(this,core,worker,ids.get(w),t(moving?"Move into":"Copy into"),this::t,folder->{
            String title=t(moving?"Moving":"Copying");String route=lastSegment(path)+" → "+(ids.get(w).isEmpty()?lastSegment(folder):names.get(w)+" · "+lastSegment(folder));
            runOperation(title,route,()->core.callAttr("transfer_items",from,sources.toString(),ids.get(w),folder,moving),value->toast(t(moving?"Moved":"Copied")+" · "+route));},this::error);
        if(names.size()==1){chosenDevice.accept(0);return;}
        dialog().setTitle(t("Choose destination device")).setItems(names.toArray(new String[0]),(d,w)->chosenDevice.accept(w)).setNegativeButton(t("Cancel"),null).show();}
    String lastSegment(String p){if(p==null||p.equals("/")||p.isEmpty())return t("Files");return p.substring(p.lastIndexOf('/')+1);}
    void duplicate(String selected){runOperation(t("Duplicate"),lastSegment(path),()->core.callAttr("duplicate_item",selected),value->toast(t("Created")+" · "+value.optString("file")));}
    void extract(String selected){runOperation(t("Extract here"),lastSegment(path),()->core.callAttr("extract_archive",selected),value->toast(t("Extracted to")+" · "+value.optString("folder")));}
    void compress(List<String> names){if(names.isEmpty())return;JSONArray paths=new JSONArray();for(String n:names)paths.put(path+"/"+n);String suggested=names.size()==1?names.get(0).replaceAll("\\.[^.]*$",""):t("Archive");
        EditText field=new EditText(this);field.setSingleLine(true);field.setText(suggested);field.selectAll();
        dialog().setTitle(t("Compress")).setMessage(names.size()+" → ZIP").setView(padded(field)).setNegativeButton(t("Cancel"),null).setPositiveButton(t("Compress"),(d,w)->{String value=field.getText().toString().trim().isEmpty()?suggested:field.getText().toString().trim();
            runOperation(t("Compress"),lastSegment(path),()->core.callAttr("compress_items",paths.toString(),value),result->toast(t("Created")+" · "+result.optString("file")));}).show();}

    // ---------- progress sheet ----------
    interface Task{PyObject run()throws Exception;}
    void runOperation(String title,String route,Task task,java.util.function.Consumer<JSONObject> done){
        if(operationRunning){error(new Exception(t("The same transfer is already running.")));return;}
        operationRunning=true;progressStopped=false;progressStarted=System.currentTimeMillis();operationTitle=title;
        LinearLayout box=ui.column();box.addView(ui.text(title,22,ui.text,true));TextView where=ui.text(route,14,ui.secondary,false);where.setSingleLine(true);where.setEllipsize(TextUtils.TruncateAt.MIDDLE);where.setPadding(0,dp(2),0,dp(16));box.addView(where);
        progressName=ui.text(t("Preparing files…"),16,ui.text,true);progressName.setSingleLine(true);progressName.setEllipsize(TextUtils.TruncateAt.MIDDLE);box.addView(progressName);
        progressBar=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);progressBar.setMax(1000);progressBar.setIndeterminate(true);progressBar.setProgressTintList(android.content.res.ColorStateList.valueOf(ui.accent));progressBar.setIndeterminateTintList(android.content.res.ColorStateList.valueOf(ui.accent));
        LinearLayout.LayoutParams bp=new LinearLayout.LayoutParams(-1,dp(10));bp.setMargins(0,dp(10),0,dp(6));box.addView(progressBar,bp);
        LinearLayout numbers=ui.rowLayout();progressBytes=ui.text(" ",14,ui.text,false);progressPercent=ui.text("",14,ui.accent,true);numbers.addView(progressBytes,new LinearLayout.LayoutParams(0,-2,1));numbers.addView(progressPercent);box.addView(numbers);
        progressSpeed=ui.text(t("Calculating time left…"),13,ui.secondary,false);progressSpeed.setPadding(0,dp(4),0,dp(18));box.addView(progressSpeed);
        LinearLayout buttons=ui.rowLayout();Button hide=ui.pill(t("Hide"),Ui.blend(ui.surface,ui.accent,0.16f),ui.accent,()->{if(progressSheet!=null)progressSheet.dismiss();});
        Button stop=ui.pill(t("Stop"),Ui.blend(ui.surface,ui.danger,0.16f),ui.danger,null);stop.setOnClickListener(v->{stop.setEnabled(false);progressStopped=true;progressName.setText(t("Stopping…"));new Thread(()->{try{core.callAttr("cancel_operation");}catch(Exception ignored){}}).start();});
        LinearLayout.LayoutParams hp=new LinearLayout.LayoutParams(0,dp(50),1);hp.setMargins(0,0,dp(10),0);buttons.addView(hide,hp);buttons.addView(stop,new LinearLayout.LayoutParams(0,dp(50),1));box.addView(buttons);
        TextView note=ui.text(t("Hiding keeps it running; see Transfers."),12,ui.tertiary,false);note.setGravity(Gravity.CENTER);note.setPadding(0,dp(12),0,0);box.addView(note);
        progressSheet=ui.sheet(box,true);progressSheet.setOnDismissListener(d->progressSheet=null);progressSheet.show();stop.post(()->stop.requestFocus());
        if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED&&!getSharedPreferences("soovee",0).getBoolean("asked_notifications",false)){getSharedPreferences("soovee",0).edit().putBoolean("asked_notifications",true).apply();requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS},23);}
        OperationService.start(this,title);
        worker.execute(()->{try{PyObject result=task.run();String json=result==null?"{}":result.toString();JSONObject value;try{value=new JSONObject(json);}catch(JSONException notObject){value=new JSONObject();}JSONObject finalValue=value;String snapshot=core.callAttr("snapshot").toString();
            runOnUiThread(()->{finishOperation();update(snapshot);if(screen.equals("files"))refreshFiles();done.accept(finalValue);});
        }catch(Exception e){boolean stopped=progressStopped;runOnUiThread(()->{finishOperation();if(screen.equals("files"))refreshFiles();if(stopped)toast(t("Stopped. Finished files stay at the destination."));});if(!stopped)error(e);}});
    }
    void finishOperation(){operationRunning=false;if(progressSheet!=null)progressSheet.dismiss();progressSheet=null;OperationService.stop(this);if(browser!=null)browser.endSelection();}
    void updateProgress(JSONObject event){
        long bytes=event.optLong("bytes"),total=event.optLong("total");int files=event.optInt("total_files",event.optInt("files")),completed=event.optInt("completed");
        String current=event.optString("current");if(!current.isEmpty())current=current.substring(current.lastIndexOf('/')+1);
        int percent=total>0?(int)Math.min(100,bytes*100/total):-1;
        String size=android.text.format.Formatter.formatShortFileSize(this,bytes)+(total>0?" "+t("of")+" "+android.text.format.Formatter.formatShortFileSize(this,total):"");
        double elapsed=(System.currentTimeMillis()-progressStarted)/1000.0;String speed="";
        if(elapsed>1&&bytes>0){double rate=bytes/elapsed;speed=android.text.format.Formatter.formatShortFileSize(this,(long)rate)+"/s";
            if(total>bytes){long left=Math.max(1,(long)((total-bytes)/rate));speed+=" · "+t("about")+" "+String.format(t("%@ left").replace("%@","%s"),left>=3600?(left/3600)+" h "+((left%3600)/60)+" min":left>=60?(left/60)+" min "+(left%60)+" s":left+" s");}
            if(files>1)speed+=" · "+String.format(t("file %ld of %ld").replace("%ld","%d"),Math.min(completed+1,files),files);}
        if(progressSheet!=null){if(!current.isEmpty()&&!progressStopped)progressName.setText(current);if(percent>=0){progressBar.setIndeterminate(false);progressBar.setProgress(percent*10);progressPercent.setText(percent+" %");}progressBytes.setText(size);if(!speed.isEmpty())progressSpeed.setText(speed);}
        OperationService.progress(this,operationTitle,(current.isEmpty()?"":current+" · ")+size,percent);
        if(screen.equals("transfers"))renderTransfers(event);
    }

    // ---------- Transfers ----------
    void showTransfers(){page("transfers",3).addView(ui.largeTitle(t("Transfers")));if(core==null)return;worker.execute(()->{try{String json=core.callAttr("operation_snapshot").toString();runOnUiThread(()->{if(screen.equals("transfers"))try{renderTransfers(new JSONObject(json));}catch(JSONException e){error(e);}});}catch(Exception e){error(e);}});}
    void renderTransfers(JSONObject value){
        while(content.getChildCount()>1)content.removeViewAt(1);String status=value.optString("status");boolean running=status.equals("running");
        if(value.length()==0)content.addView(ui.section(t("Activity"),Collections.singletonList(ui.row("history",0xff8e8e93,t("No transfers yet."),t("Copies, moves and archives appear here."),null,false,null)),null));
        else{Map<String,String> names=new HashMap<>();names.put("copy","Copy");names.put("move","Move");names.put("extract","Extract here");names.put("compress","Compress");
            Map<String,String> states=new HashMap<>();states.put("running","Running");states.put("done","Completed");states.put("error","Failed");states.put("canceled","Canceled");
            int color=running?0xff0a84ff:status.equals("done")?0xff34c759:status.equals("error")?0xffff3b30:0xff8e8e93;
            ArrayList<View> rows=new ArrayList<>();long total=value.optLong("total");String size=android.text.format.Formatter.formatShortFileSize(this,value.optLong("bytes"))+(total>0?" / "+android.text.format.Formatter.formatShortFileSize(this,total):"");
            rows.add(ui.row(running?"refresh":status.equals("done")?"check":"info",color,t(names.getOrDefault(value.optString("action"),"Transfers")),t(states.getOrDefault(status,status)),value.optInt("completed")+"/"+value.optInt("total_files",value.optInt("files"))+" · "+size,false,null));
            String current=value.optString("current");if(!current.isEmpty())rows.add(ui.row("file",0xff8e8e93,t("Current file"),current.substring(current.lastIndexOf('/')+1),null,false,null));
            if(!value.optString("destination").isEmpty())rows.add(ui.row("folder",0xff8e8e93,t("Destination"),value.optString("destination"),null,false,null));
            if(status.equals("error")&&!value.optString("message").isEmpty())rows.add(ui.row("info",0xffff3b30,t("Error"),t(value.optString("message")),null,false,null));
            content.addView(ui.section(t(running?"In progress":"Last operation"),rows,running?t("Keep Soovee open until it finishes."):null));
            if(running)content.addView(ui.section(null,Collections.singletonList(ui.row(null,ui.danger,t("Stop"),null,null,false,()->new Thread(()->{try{core.callAttr("cancel_operation");}catch(Exception ignored){}}).start())),null));
        }
        content.addView(ui.section(t("Support"),Collections.singletonList(ui.row("log",0xff8e8e93,t("Diagnostic log"),t("Errors and events, for troubleshooting"),null,true,this::showLog)),null));
    }

    // ---------- Devices ----------
    void showNearby(){LinearLayout c=page("nearby",2);c.addView(ui.largeTitle(t("Devices")));
        ArrayList<View> pairedRows=new ArrayList<>();JSONArray peers=state.optJSONArray("peers");HashSet<String> ids=new HashSet<>();
        if(peers!=null)for(int i=0;i<peers.length();i++){JSONObject p=peers.optJSONObject(i);String id=p.optString("id");ids.add(id);NetworkDiscovery.Device near=nearby(id);
            LinearLayout row=ui.row(kindIcon(near==null?"":near.kind),near!=null?0xff34c759:0xff8e8e93,p.optString("name"),t(near!=null?"On this network":"Not found on this network"),null,true,()->openDevice(id));
            row.addView(ui.moreButton(String.format(t("More for %@").replace("%@","%s"),p.optString("name")),v->{PopupMenu m=new PopupMenu(this,v);m.getMenu().add(0,1,1,t("Open"));m.getMenu().add(0,2,2,t("Remove pairing"));m.setOnMenuItemClickListener(x->{if(x.getItemId()==1)openDevice(id);else removePairing(id,p.optString("name"),false);return true;});m.show();}));
            pairedRows.add(row);}
        c.addView(ui.section(t("Paired devices"),pairedRows,pairedRows.isEmpty()?t("No paired devices yet. Pair one below."):t("Tap a device to browse its shared folders. Use … to remove a pairing.")));
        ArrayList<View> nearRows=new ArrayList<>();List<NetworkDiscovery.Device> values=network==null?Collections.emptyList():network.snapshot();
        for(NetworkDiscovery.Device d:values){if(ids.contains(d.id))continue;nearRows.add(ui.row(kindIcon(d.kind),ui.accent,d.name,t("Tap to pair"),t("Pair"),false,()->requestCode(d)));}
        if(nearRows.isEmpty()){LinearLayout row=ui.row(null,0,t("Looking for devices…"),null,null,false,null);ProgressBar spin=new ProgressBar(this);row.addView(spin,new LinearLayout.LayoutParams(dp(22),dp(22)));nearRows.add(row);}
        c.addView(ui.section(t("Nearby"),nearRows,t("The other device shows a code after you tap it. Both devices need Soovee open and the same Wi-Fi.")));
        ArrayList<View> add=new ArrayList<>();
        if(!television)add.add(ui.row("qr",0xff0a84ff,t("Scan QR code"),null,null,true,this::scanQr));
        add.add(ui.row("info",0xff5e5ce6,t(television?"Show this TV’s code":"Show this device’s code"),t("For pairing started on the other device"),null,true,this::showPairing));
        add.add(ui.row("link",0xff30b0c7,t("Connect by address…"),null,null,true,this::joinDialog));
        c.addView(ui.section(t("Add a device"),add,state.optString("name")+" · "+(state.optBoolean("localNetwork",true)?state.optString("address"):t("not connected to Wi-Fi"))));
    }
    void scanQr(){scanner.launch(new com.journeyapps.barcodescanner.ScanOptions().setDesiredBarcodeFormats(com.journeyapps.barcodescanner.ScanOptions.QR_CODE).setBeepEnabled(false).setOrientationLocked(false).setPrompt(t("Scan pairing QR")));}
    void requestCode(NetworkDiscovery.Device device){worker.execute(()->{boolean asked=false;try{asked=new JSONObject(core.callAttr("request_pairing",device.host,device.port).toString()).optBoolean("asked");}catch(Exception ignored){}final boolean shown=asked;runOnUiThread(()->askCode(device,shown));});}
    void askCode(NetworkDiscovery.Device device,boolean asked){EditText pin=new EditText(this);pin.setHint(t("Eight-digit code"));pin.setInputType(2);
        AlertDialog.Builder b=dialog().setTitle(device.name).setMessage(t(asked?"The device now shows a pairing code. Type it here, or scan its QR.":"Open Soovee on the device and type the pairing code it shows, or scan its QR.")).setView(padded(pin))
            .setNegativeButton(t("Cancel"),null).setPositiveButton(t("Pair"),(d,w)->callState("pair","",device.host,Integer.toString(device.port),pin.getText().toString()));
        if(!television)b.setNeutralButton(t("Scan QR instead"),(d,w)->scanQr());
        AlertDialog dialog=b.create();dialog.setOnShowListener(v->{Button pair=dialog.getButton(-1);pair.setEnabled(false);pin.addTextChangedListener(new android.text.TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int c,int f){}public void onTextChanged(CharSequence s,int a,int c,int f){pair.setEnabled(s.toString().replaceAll("\\D","").length()==8);}public void afterTextChanged(android.text.Editable e){}});});dialog.show();}
    void joinDialog(){LinearLayout form=ui.column();EditText invite=new EditText(this),host=new EditText(this),port=new EditText(this),pin=new EditText(this);
        invite.setHint(t("Paste Soovee invitation"));host.setHint(t("Local IP address"));port.setHint(t("Port"));pin.setHint(t("Eight-digit code"));port.setInputType(2);pin.setInputType(2);for(EditText f:new EditText[]{invite,host,port,pin})form.addView(f);
        dialog().setTitle(t("Pair device")).setView(padded(form)).setNegativeButton(t("Cancel"),null).setPositiveButton(t("Pair"),(d,w)->callState("pair",invite.getText().toString(),host.getText().toString(),port.getText().toString(),pin.getText().toString())).show();}
    void removePairing(String id,String name,boolean again){dialog().setTitle(t("Remove pairing")).setMessage(String.format(t("Remove %@? Files on both devices stay. To connect again, pair with a new code.").replace("%@","%s"),name))
        .setNegativeButton(t("Cancel"),null).setPositiveButton(t("Remove pairing"),(d,w)->worker.execute(()->{try{String value=core.callAttr("remove_pairing",id).toString();runOnUiThread(()->{update(value);showNearby();if(again){NetworkDiscovery.Device near=nearby(id);if(near!=null)requestCode(near);}});}catch(Exception e){error(e);}})).show();}
    /** Open a paired device's shared folders, or say clearly why it cannot be opened. */
    void openDevice(String id){if(state.optString("role").equals("controlled")){error(new Exception(t("Enable both directions in Device role first.")));return;}
        LinearLayout c=page("connecting",2);c.addView(ui.largeTitle(deviceName(id)));c.addView(new ProgressBar(this));
        worker.execute(()->{try{NetworkDiscovery.Device near=nearby(id);if(near!=null)core.callAttr("reconnect",id,near.host,near.port);
            JSONObject value=new JSONObject(core.callAttr("connection_status",id).toString());
            runOnUiThread(()->{if(!screen.equals("connecting"))return;if(value.optString("status").equals("ready")){peer=id;openFolder("/");}else showConnection(id,value.optString("status"),value.optString("message"));});}catch(Exception e){error(e);}});}
    void showConnection(String id,String status,String message){String name=deviceName(id);LinearLayout c=page("connection",2);c.addView(ui.backLink(t("Devices"),this::showNearby));c.addView(ui.largeTitle(name));
        if(status.equals("not_recognized")){c.addView(ui.section(t("Pair this device again"),Collections.singletonList(ui.row("refresh",ui.accent,t("Remove and pair again"),null,null,true,()->removePairing(id,name,true))),t("The other device no longer knows this device, for example because the pairing was removed there. Remove the old pairing here and pair again with a new code. Files on both devices stay.")));return;}
        boolean empty=status.equals("no_shared_folders");
        c.addView(ui.section(t(empty?"Paired · choose what to share":"Device is currently unavailable"),Collections.singletonList(ui.row("refresh",0xff0a84ff,t("Check again"),null,null,true,()->openDevice(id))),
            t(empty?"The devices are paired, but the other device has not shared any folders with this device yet. On the computer, open Soovee Transfers → Shared folders, choose this device and click Share folder…. Then tap Check again.":"Keep Soovee open on both devices and connect them to the same local network.")));
        c.addView(ui.section(null,Collections.singletonList(ui.row(null,ui.danger,t("Remove pairing"),null,null,false,()->removePairing(id,name,false))),null));}
    void showPairing(){LinearLayout c=page("pair",2);peer="";path="/";lastInvitation="";
        c.addView(ui.backLink(t("Devices"),this::showNearby));c.addView(ui.largeTitle(t(television?"This TV’s code":"This device’s code")));
        TextView hint=ui.text(t("On the other device, choose this device and type the code, or scan the QR in Soovee."),15,ui.secondary,false);hint.setPadding(dp(4),0,0,dp(16));c.addView(hint);
        LinearLayout card=new LinearLayout(this);card.setOrientation(television?LinearLayout.HORIZONTAL:LinearLayout.VERTICAL);card.setGravity(Gravity.CENTER);card.setPadding(dp(20),dp(20),dp(20),dp(20));card.setBackground(ui.round(ui.surface,20));
        qr=new ImageView(this);qr.setBackgroundColor(-1);qr.setPadding(dp(8),dp(8),dp(8),dp(8));qr.setContentDescription(t("Soovee pairing QR"));int side=dp(television?240:220);card.addView(qr,new LinearLayout.LayoutParams(side,side));
        LinearLayout text=ui.column();text.setGravity(television?Gravity.START:Gravity.CENTER_HORIZONTAL);text.setPadding(dp(television?28:0),dp(television?0:16),0,0);
        code=ui.text("",television?44:38,ui.text,true);code.setTypeface(Typeface.MONOSPACE,Typeface.BOLD);text.addView(code);address=ui.text("",15,ui.secondary,false);text.addView(address);expiry=ui.text("",13,ui.tertiary,false);text.addView(expiry);
        card.addView(text);c.addView(card);View gap=new View(this);c.addView(gap,new LinearLayout.LayoutParams(1,dp(18)));
        ArrayList<View> rows=new ArrayList<>();rows.add(ui.row("refresh",ui.accent,t("Generate new code"),null,null,false,()->callState("renew")));
        if(!television)rows.add(ui.row("copy",0xff8e8e93,t("Copy pairing invitation"),null,null,false,()->((ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Soovee",state.optString("invitation")))));
        c.addView(ui.section(null,rows,null));update(state.toString());}
    void showPairingRequest(String name){showPairing();TextView who=ui.text(String.format(t("%@ wants to pair. Type this code there, or scan the QR.").replace("%@","%s"),name),television?22:17,ui.accent,true);who.setPadding(dp(4),0,0,dp(12));content.addView(who,2);}

    // ---------- Settings ----------
    void showSettings(){LinearLayout c=page("settings",television?4:-1);if(!television)c.addView(ui.backLink(t("Overview"),this::showHome));c.addView(ui.largeTitle(t("Settings")));
        if(!television){String[] styles={"System","Light","Dark"};int current=getSharedPreferences("soovee",0).getInt("appearance",0);
            c.addView(ui.section(t("Appearance"),Collections.singletonList(ui.row("palette",0xff5e5ce6,t("Theme"),null,t(styles[current]),true,()->dialog().setTitle(t("Theme")).setSingleChoiceItems(new String[]{t(styles[0]),t(styles[1]),t(styles[2])},current,(d,w)->{d.dismiss();getSharedPreferences("soovee",0).edit().putInt("appearance",w).apply();buildShell();showSettings();}).show())),null));}
        ArrayList<View> storage=new ArrayList<>();boolean sharing=state.optBoolean("storageSharing");
        storage.add(ui.row("storage",0xff0a84ff,t(sharing?"Stop sharing device storage":"Allow access to device storage…"),t(sharing?"Paired devices can browse device storage":"Only the Soovee folder is shared"),null,true,sharing?()->dialog().setTitle(t("Stop sharing device storage")).setMessage(t("Paired devices will keep access to the app Shared folder only.")).setNegativeButton(t("Cancel"),null).setPositiveButton(android.R.string.ok,(d,w)->{getSharedPreferences("soovee",0).edit().putBoolean("share_storage",false).apply();refreshStorage();}).show():this::allowStorage));
        c.addView(ui.section(t("Files"),storage,null));
        boolean controlled=state.optString("role").equals("controlled");
        ArrayList<View> transfers=new ArrayList<>();
        transfers.add(ui.row("edit",0xffff9500,t("Device name"),null,state.optString("name"),true,()->{EditText field=new EditText(this);field.setText(state.optString("name"));dialog().setTitle(t("Device name")).setView(padded(field)).setNegativeButton(t("Cancel"),null).setPositiveButton(android.R.string.ok,(d,w)->callState("set_name",field.getText().toString())).show();}));
        transfers.add(ui.row("swap",0xffff9500,t("Device role"),null,t(controlled?"Controlled device":"Both directions"),true,()->dialog().setTitle(t("Device role")).setSingleChoiceItems(new String[]{t("Both directions"),t("Controlled device")},controlled?1:0,(d,w)->{d.dismiss();callState("set_role",w==1?"controlled":"both");}).show()));
        transfers.add(ui.row("devices",0xff34c759,t("Devices"),null,null,true,this::showNearby));
        c.addView(ui.section(t("Transfers"),transfers,t(controlled?"Other devices can use folders shared from this device, but this device cannot open theirs.":"This device can open folders shared by paired devices, and they can open folders you share.")));
        ArrayList<View> support=new ArrayList<>();
        support.add(ui.row("log",0xff8e8e93,t("Diagnostic log"),t("Errors and events, for troubleshooting"),null,true,this::showLog));
        support.add(ui.row("info",0xff8e8e93,t("About"),null,versionName(),true,()->dialog().setTitle("Soovee Commander "+versionName()).setMessage(t("Open source under MIT. Device storage is available after permission and sharing consent. CPython: PSF, Chaquopy: MIT, SPAKE2: MIT, qrcode: BSD-3-Clause, AndroidX: Apache-2.0.")).setPositiveButton(android.R.string.ok,null).show()));
        support.add(ui.row("file",0xff8e8e93,t("Third-party licenses"),null,null,true,this::showLicenses));
        c.addView(ui.section(t("Support"),support,null));}
    String versionName(){try{return getPackageManager().getPackageInfo(getPackageName(),0).versionName;}catch(Exception e){return "";}}
    void showLog(){worker.execute(()->{try{String raw=core.callAttr("diagnostics").toString();StringBuilder out=new StringBuilder();
        for(String line:raw.split("\n")){if(line.trim().isEmpty())continue;try{JSONObject e=new JSONObject(line);String time=e.optString("time");time=time.length()>=19?time.substring(5,19).replace('T',' '):time;out.append(time).append("  ").append(e.optString("level").equals("ERROR")?"⚠ ":"").append(e.optString("event"));
            String tb=e.optString("traceback").trim();if(!tb.isEmpty())out.append("\n      ").append(tb.substring(tb.lastIndexOf('\n')+1));out.append('\n');}catch(JSONException plain){out.append(line).append('\n');}}
        String text=out.length()==0?t("The log is empty."):out.toString();
        runOnUiThread(()->{Dialog d=new Dialog(this,android.R.style.Theme_DeviceDefault_NoActionBar);LinearLayout box=ui.column();box.setBackgroundColor(ui.bg);box.setFitsSystemWindows(true);
            LinearLayout bar=ui.rowLayout();bar.setPadding(dp(8),dp(8),dp(8),dp(8));bar.addView(ui.pill(t("Done"),ui.surface,ui.text,d::dismiss));TextView title=ui.text(t("Diagnostic log"),16,ui.text,true);title.setGravity(Gravity.CENTER);bar.addView(title,new LinearLayout.LayoutParams(0,-2,1));
            bar.addView(ui.pill(t("Share"),ui.accent,ui.onAccent,()->startActivity(Intent.createChooser(new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,text),t("Share log")))));box.addView(bar);
            TextView body=ui.text(text,12,ui.text,false);body.setTypeface(Typeface.MONOSPACE);body.setTextIsSelectable(true);body.setPadding(dp(16),dp(8),dp(16),dp(24));ScrollView sv=new ScrollView(this);sv.addView(body);box.addView(sv,new LinearLayout.LayoutParams(-1,0,1));
            d.setContentView(box);d.show();sv.post(()->sv.fullScroll(View.FOCUS_DOWN));});}catch(Exception e){error(e);}});}
    void showLicenses(){try{ArrayList<String> files=new ArrayList<>();for(String name:getAssets().list(""))if(name.endsWith(".txt"))files.add(name);Collections.sort(files);
        dialog().setTitle(t("Third-party licenses")).setItems(files.toArray(new String[0]),(dialog,index)->{try(InputStream in=getAssets().open(files.get(index))){TextView text=ui.text(new String(readAll(in),StandardCharsets.UTF_8),13,0xff14233a,false);text.setTextIsSelectable(true);text.setPadding(dp(18),dp(8),dp(18),dp(8));ScrollView sv=new ScrollView(this);sv.addView(text);dialog().setTitle(files.get(index)).setView(sv).setPositiveButton(android.R.string.ok,null).show();}catch(Exception e){error(e);}})
            .setNegativeButton(t("Cancel"),null).show();}catch(Exception e){error(e);}}

    // ---------- core calls, storage, import ----------
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);if(ready&&intent.getDataString()!=null)callState("pair",intent.getDataString(),"","0","");}
    void callState(String name,Object... args){HashSet<String> before=new HashSet<>();JSONArray peers=state.optJSONArray("peers");if(peers!=null)for(int i=0;i<peers.length();i++)before.add(peers.optJSONObject(i).optString("id"));
        worker.execute(()->{try{String value=core.callAttr(name,args).toString();runOnUiThread(()->{update(value);
            if(name.equals("pair")){JSONArray after=state.optJSONArray("peers");if(after!=null)for(int i=0;i<after.length();i++){String id=after.optJSONObject(i).optString("id");if(!before.contains(id)&&!television){openDevice(id);return;}}showNearby();}
            else if(name.equals("set_name")||name.equals("set_role"))showSettings();else if(name.equals("renew"))update(value);else showHome();});}catch(Exception e){error(e);}});}
    void chooseUpload(){try{uploadPeer=peer;uploadPath=path;Intent picker=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE);picker.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true);startActivityForResult(picker,7);}catch(Exception e){uploadPeer="";uploadPath="";error(e);}}
    String storageState()throws Exception{return core.callAttr("configure_storage",DeviceStorage.roots(this).toString(),getSharedPreferences("soovee",0).getBoolean("share_storage",false)&&DeviceStorage.permitted(this)).toString();}
    void refreshStorage(){if(!ready)return;worker.execute(()->{try{String value=storageState();runOnUiThread(()->{update(value);if(screen.equals("settings"))showSettings();else if(screen.equals("home"))showHome();});}catch(Exception e){error(e);}});}
    @Override protected void onResume(){super.onResume();refreshStorage();}
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results){super.onRequestPermissionsResult(request,permissions,results);if(request==17)refreshStorage();}
    void allowStorage(){dialog().setTitle(t("Share device storage"))
        .setMessage(t("Allow approved paired devices to browse and copy files in internal shared storage and connected USB drives? Other apps’ private data stays protected. Android will ask for storage permission."))
        .setNegativeButton(t("Cancel"),null).setPositiveButton(t("Continue"),(d,w)->{getSharedPreferences("soovee",0).edit().putBoolean("share_storage",true).apply();
            if(DeviceStorage.permitted(this)){refreshStorage();return;}
            try{if(Build.VERSION.SDK_INT>=30){Intent settings=new Intent(android.provider.Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,Uri.parse("package:"+getPackageName()));try{startActivity(settings);}catch(ActivityNotFoundException missing){startActivity(new Intent(android.provider.Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));}}
                else requestPermissions(new String[]{android.Manifest.permission.READ_EXTERNAL_STORAGE,android.Manifest.permission.WRITE_EXTERNAL_STORAGE},17);}catch(Exception e){error(e);}}).show();}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request!=7||result!=RESULT_OK||data==null)return;ArrayList<Uri> values=new ArrayList<>();if(data.getClipData()!=null)for(int i=0;i<data.getClipData().getItemCount();i++)values.add(data.getClipData().getItemAt(i).getUri());else if(data.getData()!=null)values.add(data.getData());
        String targetPeer=uploadPeer,targetPath=uploadPath;uploadPeer="";uploadPath="";
        worker.execute(()->{try{for(Uri uri:values){String name="imported-file";try(Cursor cursor=getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)){if(cursor!=null&&cursor.moveToFirst())name=cursor.getString(0);}try(ParcelFileDescriptor fd=getContentResolver().openFileDescriptor(uri,"r")){core.callAttr("import_file",name,fd.getFd());}
            if(!targetPeer.isEmpty())core.callAttr("upload_from",targetPeer,targetPath,"/Shared/"+name);else if(!targetPath.isEmpty()&&!targetPath.equals("/")&&!targetPath.equals("/Shared"))core.callAttr("copy_local_item","/Shared/"+name,targetPath,true);}
            runOnUiThread(()->{peer=targetPeer;openFolder(targetPath.isEmpty()||targetPath.equals("/")?"/Shared":targetPath);toast(t("Imported"));});}catch(Exception e){error(e);}});}
    void toast(String text){Toast.makeText(this,text,Toast.LENGTH_SHORT).show();}

    /** Python workers call this; every pairing explicitly grants only the Shared folder. */
    public boolean approve(String kind,String payload){CountDownLatch done=new CountDownLatch(1);AtomicBoolean accepted=new AtomicBoolean(false);runOnUiThread(()->{if(isFinishing()){done.countDown();return;}try{JSONObject request=new JSONObject(payload);
        String message=kind.equals("pair")?t("Confirm pairing with this device:")+"\n"+request.optString("name")+"\n"+request.optString("host")+"\n"+t("Verification:")+" "+request.optString("verification")+"\n\n"+t(request.optBoolean("storageSharing")?"Allow this device to browse and copy files in the shared device storage? Other apps’ private files remain protected.":"Allow this device to browse and upload to this app’s Shared folder? Other folders are not shared.")
            :t("Receive files from this device?")+"\n"+request.optString("name")+" · "+request.optInt("files")+" · "+android.text.format.Formatter.formatShortFileSize(this,request.optLong("bytes"));
        AlertDialog dialog=dialog().setTitle(t("Confirm device access")).setMessage(message).setNegativeButton(t("Cancel"),(d,w)->done.countDown()).setPositiveButton(t("Allow"),(d,w)->{accepted.set(true);done.countDown();}).create();dialog.setOnDismissListener(d->{approvals.remove(dialog);done.countDown();});approvals.add(dialog);dialog.show();dialog.getButton(-2).requestFocus();timer.postDelayed(()->{if(dialog.isShowing())dialog.dismiss();},120000);
    }catch(Exception e){done.countDown();error(e);}});try{if(!done.await(120,TimeUnit.SECONDS))return false;}catch(InterruptedException e){Thread.currentThread().interrupt();return false;}return accepted.get();}
    public void activity(String payload){runOnUiThread(()->{if(!isFinishing())try{JSONObject event=new JSONObject(payload);String kind=event.optString("kind");
        if(kind.equals("pair-request")){showPairingRequest(event.optString("name"));return;}
        if(kind.equals("paired"))worker.execute(()->{try{String value=core.callAttr("snapshot").toString();runOnUiThread(()->{update(value);if(screen.equals("pair"))showNearby();});}catch(Exception ignored){}});
        if(kind.equals("operation"))updateProgress(event);}catch(Exception ignored){}});}
    void error(Exception e){String original=e.getMessage()==null?e.getClass().getSimpleName():e.getMessage();if(core!=null&&!worker.isShutdown())worker.execute(()->{try{core.callAttr("record_error",original);}catch(Exception ignored){}});
        String message=original.split("\n",2)[0].replaceFirst("^(?:[A-Za-z]+Error|PairingNotRecognized|Cancelled):\\s*","");
        runOnUiThread(()->{if(!isFinishing())dialog().setTitle(t("Soovee · Error")).setMessage(t(message)).setPositiveButton(android.R.string.ok,null).show();});}
    @Override public void onBackPressed(){
        if(browser!=null&&(browser.selecting||!browser.selection.isEmpty())){browser.endSelection();return;}
        if(screen.equals("files")){if(searchQuery!=null){openFolder(path);return;}if(!path.equals("/")){int s=path.lastIndexOf('/');openFolder(s<=0?"/":path.substring(0,s));return;}if(!peer.isEmpty()){peer="";showNearby();return;}}
        if(!screen.equals("home")){showHome();return;}super.onBackPressed();}
    @Override protected void onDestroy(){ready=false;timer.removeCallbacksAndMessages(null);if(network!=null)network.close();for(AlertDialog dialog:new ArrayList<>(approvals))dialog.dismiss();if(core!=null)worker.execute(()->core.callAttr("stop",this));worker.shutdown();OperationService.stop(this);super.onDestroy();}
}
