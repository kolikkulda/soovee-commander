package cz.soovee.commander;

import android.app.*;
import android.content.*;
import android.content.res.Configuration;
import android.database.Cursor;
import android.graphics.*;
import android.graphics.drawable.*;
import android.net.Uri;
import android.os.*;
import android.provider.OpenableColumns;
import android.view.*;
import android.widget.*;
import androidx.core.content.FileProvider;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;
import org.json.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** D-pad and touch UI. Authorization and filesystem safety stay in the shared core. */
public class MainActivity extends androidx.activity.ComponentActivity {
    final androidx.activity.result.ActivityResultLauncher<com.journeyapps.barcodescanner.ScanOptions> scanner = registerForActivityResult(new com.journeyapps.barcodescanner.ScanContract(), result -> {
        if(result.getContents()!=null)callState("pair",result.getContents(),"","0","");
    });
    final int BG=0xff0a1122, SURFACE=0xff14233a, CYAN=0xff1adce6;
    final ExecutorService worker=Executors.newSingleThreadExecutor();
    final Handler timer=new Handler(Looper.getMainLooper());
    final Set<AlertDialog> approvals=new HashSet<>();
    LinearLayout content; TextView status,code,address,expiry; ImageView qr;
    PyObject core; JSONObject state=new JSONObject(), translations=new JSONObject();
    String screen="home",peer="",path="/",lastInvitation="",uploadPeer="",uploadPath=""; boolean television,ready=false;
    NetworkDiscovery network;
    final AtomicBoolean snapshotPending=new AtomicBoolean(false);
    final Map<String,TextView> storageLabels=new HashMap<>();
    Runnable refresh;
    String browserSelection="";
    TextView operationText;
    int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}
    String t(String source){return translations.optString(source,source);}
    TextView label(String text,int size){TextView v=new TextView(this);v.setText(text);v.setTextSize(size);v.setTextColor(-1);v.setPadding(0,dp(6),0,dp(6));return v;}
    LinearLayout column(){LinearLayout v=new LinearLayout(this);v.setOrientation(1);return v;}
    GradientDrawable shape(int color,int border){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(12));d.setStroke(dp(2),border);return d;}
    Button button(String text,Runnable action){
        Button v=new Button(this);v.setText(text);v.setTextColor(-1);v.setTextSize(16);v.setAllCaps(false);v.setMinHeight(dp(television?46:54));v.setPadding(dp(14),dp(8),dp(14),dp(8));
        StateListDrawable colors=new StateListDrawable();colors.addState(new int[]{android.R.attr.state_focused},shape(0xff194155,CYAN));colors.addState(new int[]{android.R.attr.state_pressed},shape(0xff194155,CYAN));colors.addState(new int[]{},shape(SURFACE,0xff374f70));v.setBackground(colors);v.setOnClickListener(w->action.run());return v;
    }
    void add(LinearLayout row,String text,Runnable action){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,dp(5),0,dp(5));row.addView(button(text,action),p);}
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);
        try{if(getResources().getConfiguration().getLocales().get(0).getLanguage().equals("cs")){try(InputStream in=getAssets().open("cs.json")){ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[4096];int read;while((read=in.read(buffer))!=-1)bytes.write(buffer,0,read);translations=new JSONObject(bytes.toString("UTF-8"));}}}catch(Exception ignored){}
        television=getIntent().getBooleanExtra("tvMode",(getResources().getConfiguration().uiMode&Configuration.UI_MODE_TYPE_MASK)==Configuration.UI_MODE_TYPE_TELEVISION);
        if(television)getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN|WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout root=column();root.setFitsSystemWindows(true);root.setBackgroundColor(BG);root.setPadding(dp(television?24:18),dp(television?10:16),dp(television?24:18),dp(television?10:16));
        LinearLayout brand=new LinearLayout(this);brand.setGravity(Gravity.CENTER_VERTICAL);
        ImageView logo=new ImageView(this);logo.setImageResource(cz.soovee.commander.R.drawable.soovee_icon);LinearLayout.LayoutParams mark=new LinearLayout.LayoutParams(dp(television?32:44),dp(television?32:44));mark.setMargins(0,0,dp(12),0);brand.addView(logo,mark);
        TextView title=label("Soovee Commander",television?23:25);title.setTypeface(null,Typeface.BOLD);brand.addView(title,new LinearLayout.LayoutParams(0,-2,1));Button settings=button("⚙",this::showSettings);brand.addView(settings,new LinearLayout.LayoutParams(dp(48),dp(44)));root.addView(brand);
        status=label(t("Starting local transfers…"),television?12:14);status.setTextColor(0xff9cabc3);root.addView(status);
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);content=column();scroll.addView(content);
        if(television){LinearLayout body=new LinearLayout(this);LinearLayout nav=column();
            add(nav,"⌂  "+t("Home"),this::showHome);add(nav,"▰  "+t("Files"),()->{peer="";path="/";browse();});add(nav,"▣  "+t("Devices"),this::showNearby);add(nav,"⇄  "+t("Transfers"),this::showTransfers);add(nav,"⚙  "+t("Settings"),this::showSettings);
            LinearLayout.LayoutParams rail=new LinearLayout.LayoutParams(dp(150),-1);rail.setMargins(0,dp(10),dp(20),0);for(int i=0;i<nav.getChildCount();i++){Button item=(Button)nav.getChildAt(i);item.setGravity(Gravity.START|Gravity.CENTER_VERTICAL);item.setTextSize(15);StateListDrawable background=new StateListDrawable();background.addState(new int[]{android.R.attr.state_focused},shape(0xff1d3152,CYAN));background.addState(new int[]{},shape(0x00000000,0x00000000));item.setBackground(background);}body.addView(nav,rail);body.addView(scroll,new LinearLayout.LayoutParams(0,-1,1));root.addView(body,new LinearLayout.LayoutParams(-1,0,1));nav.post(()->nav.getChildAt(0).requestFocus());
        }else {root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));LinearLayout tabs=new LinearLayout(this);String[] names={"Home","Files","Devices","Transfers"};String[] icons={"⌂","▰","▣","⇄"};Runnable[] tasks={this::showHome,()->{peer="";path="/";browse();},this::showNearby,this::showTransfers};for(int i=0;i<4;i++){Button tab=button(icons[i]+"\n"+t(names[i]),tasks[i]);tab.setTextSize(12);tab.setPadding(0,dp(4),0,dp(4));tabs.addView(tab,new LinearLayout.LayoutParams(0,dp(64),1));}root.addView(tabs);}setContentView(root);
        worker.execute(()->{try{
            if(!Python.isStarted())Python.start(new AndroidPlatform(this));core=Python.getInstance().getModule("soovee_mobile");
            String value=core.callAttr("start",new File(getFilesDir(),"transfer-state").toString(),new File(getFilesDir(),"Shared").toString(),Build.MODEL,television?"tv":"phone",this).toString();
            value=storageState();
            android.util.Log.i("SooveeCommander","Transfers ready · "+core.callAttr("runtime_check").toString());
            String initial=value;
            runOnUiThread(()->{ready=true;update(initial);showHome();if(getIntent().getDataString()!=null)callState("pair",getIntent().getDataString(),"","0","");});
        }catch(Exception e){error(e);}});
        refresh=new Runnable(){public void run(){if(ready&&snapshotPending.compareAndSet(false,true))worker.execute(()->{try{String value=core.callAttr("snapshot").toString();runOnUiThread(()->update(value));}catch(Exception e){error(e);}finally{snapshotPending.set(false);}});timer.postDelayed(this,3000);}};timer.postDelayed(refresh,3000);
    }
    void update(String value){if(isFinishing())return;try{
        state=new JSONObject(value);status.setText(television?state.optString("name")+" · "+t("Ready on your local network"):t("Local network")+" · "+state.optString("address")+":"+state.optInt("port"));
        if(screen.equals("storage")){JSONArray volumes=state.optJSONArray("storage");if(volumes!=null)for(int i=0;i<volumes.length();i++){JSONObject volume=volumes.optJSONObject(i);TextView field=storageLabels.get(volume.optString("key"));if(field!=null)field.setText(storageCaption(volume));}}
        if(ready&&!state.optString("id").isEmpty()&&(network==null||!network.name.equals(state.optString("name"))||network.port!=state.optInt("port"))){
            if(network!=null)network.close();network=new NetworkDiscovery(this,state.optString("id"),state.optString("name"),state.optInt("port"),television?"tv":"phone",()->runOnUiThread(()->{if(screen.equals("nearby"))showNearby();}));
        }
        if(!screen.equals("pair")||code==null)return;
        String pin=state.optString("code");code.setText(pin.isEmpty()?t("Generate a new code"):pin.substring(0,4)+" "+pin.substring(4));
        address.setText(state.optString("address")+":"+state.optInt("port"));expiry.setText(t("Code valid for")+" "+state.optInt("expires")+" s\n"+t("Keep this app open during transfers."));
        JSONArray matrix=state.optJSONArray("qr");if(matrix==null){qr.setImageDrawable(null);lastInvitation="";return;}
        if(state.optString("invitation").equals(lastInvitation))return;lastInvitation=state.optString("invitation");
        int n=matrix.length(),scale=8;Bitmap image=Bitmap.createBitmap(n*scale,n*scale,Bitmap.Config.ARGB_8888);Canvas canvas=new Canvas(image);canvas.drawColor(-1);Paint paint=new Paint();paint.setColor(0xff000000);
        for(int y=0;y<n;y++)for(int x=0;x<n;x++)if(matrix.getJSONArray(y).getBoolean(x))canvas.drawRect(x*scale,y*scale,(x+1)*scale,(y+1)*scale,paint);qr.setImageBitmap(image);
    }catch(Exception e){error(e);}}

    void showHome(){operationText=null;screen="home";content.removeAllViews();peer="";path="/";if(television){content.addView(new TvLibraryHome(this));return;}
        TextView title=label(t(television?"TV library":"Overview"),television?28:30);title.setTypeface(null,Typeface.BOLD);content.addView(title);
        TextView subtitle=label(t("Your files. All your devices."),15);subtitle.setTextColor(0xffa5b3cc);content.addView(subtitle);
        JSONArray volumes=state.optJSONArray("storage");if(volumes!=null)for(int i=0;i<volumes.length();i++){
            JSONObject volume=volumes.optJSONObject(i);String name=volume.optString("name");LinearLayout card=column();card.setPadding(dp(18),dp(14),dp(18),dp(14));card.setBackground(shape(SURFACE,0xff293650));
            LinearLayout line=new LinearLayout(this);line.setGravity(Gravity.CENTER_VERTICAL);TextView heading=label(t(name),20);heading.setTypeface(null,Typeface.BOLD);line.addView(heading,new LinearLayout.LayoutParams(0,-2,1));Button open=button(t("Open"),()->{peer="";path="/"+name;browse();});line.addView(open);card.addView(line);
            long total=volume.optLong("total"),free=volume.optLong("free");ProgressBar meter=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);meter.setMax(1000);meter.setProgress(total>0?(int)(1000.0*(total-free)/total):0);meter.setProgressTintList(android.content.res.ColorStateList.valueOf(CYAN));card.addView(meter,new LinearLayout.LayoutParams(-1,dp(5)));
            TextView capacity=label(t("Free")+" "+android.text.format.Formatter.formatFileSize(this,free)+" · "+t("Total")+" "+android.text.format.Formatter.formatFileSize(this,total),13);capacity.setTextColor(0xffa5b3cc);card.addView(capacity);LinearLayout.LayoutParams gap=new LinearLayout.LayoutParams(-1,-2);gap.setMargins(0,dp(8),0,dp(8));content.addView(card,gap);
        }
        if(!state.optBoolean("storageSharing"))add(content,t("Allow access to device storage…"),this::allowStorage);
        TextView devices=label(t("Your devices"),20);devices.setTypeface(null,Typeface.BOLD);content.addView(devices);
        JSONArray peers=state.optJSONArray("peers");if(peers!=null)for(int i=0;i<peers.length();i++){JSONObject device=peers.optJSONObject(i);add(content,device.optString("name")+"   →",()->{peer=device.optString("id");path="/";browse();});}
        add(content,t("Find a device or scan QR"),this::showNearby);add(content,t("My QR and pairing code"),this::showPairing);
    }
    void showTransfers(){screen="transfers";content.removeAllViews();content.addView(label(t("Transfers"),26));if(core==null)return;worker.execute(()->{try{String json=core.callAttr("operation_snapshot").toString();runOnUiThread(()->{if(!screen.equals("transfers"))return;try{JSONObject value=new JSONObject(json);operationText=label(value.length()==0?t("No transfers yet."):value.optString("status")+"\n"+value.optString("current")+"\n"+value.optString("destination")+"\n"+android.text.format.Formatter.formatFileSize(this,value.optLong("bytes"))+" · "+value.optInt("completed")+" / "+value.optInt("files"),16);content.addView(operationText);add(content,t("Diagnostic log"),()->worker.execute(()->{try{String log=core.callAttr("diagnostics").toString();runOnUiThread(()->new AlertDialog.Builder(this).setTitle(t("Diagnostic log")).setMessage(log).setPositiveButton(android.R.string.ok,null).show());}catch(Exception e){error(e);}}));}catch(Exception e){error(e);}});}catch(Exception e){error(e);}});}
    void showPairing(){screen="pair";peer="";path="/";lastInvitation="";content.removeAllViews();
        content.addView(label(t("Connect your devices"),television?25:21));content.addView(label(t("Scan this QR on your phone, or select this device in Soovee and enter its code."),16));
        LinearLayout pairing=new LinearLayout(this);pairing.setOrientation(television?0:1);pairing.setPadding(dp(18),dp(14),dp(18),dp(14));pairing.setBackground(shape(SURFACE,0xff374f70));qr=new ImageView(this);qr.setContentDescription(t("Soovee pairing QR"));int side=dp(television?250:205);LinearLayout.LayoutParams q=new LinearLayout.LayoutParams(side,side);q.gravity=Gravity.CENTER_HORIZONTAL;q.setMargins(dp(6),dp(12),dp(22),dp(12));pairing.addView(qr,q);
        LinearLayout text=column();code=label("",television?38:32);code.setTypeface(Typeface.MONOSPACE,Typeface.BOLD);text.addView(code);address=label("",18);text.addView(address);expiry=label("",14);text.addView(expiry);
        add(text,t("Generate new code"),()->callState("renew"));add(text,t("Copy pairing invitation"),()->((ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Soovee",state.optString("invitation"))));
        pairing.addView(text,new LinearLayout.LayoutParams(television?0:-1,-2,television?1:0));content.addView(pairing);
        if(!television){add(content,t("Scan pairing QR"),()->scanner.launch(new com.journeyapps.barcodescanner.ScanOptions().setDesiredBarcodeFormats(com.journeyapps.barcodescanner.ScanOptions.QR_CODE).setBeepEnabled(false).setOrientationLocked(false).setPrompt(t("Scan pairing QR"))));add(content,t("Connect to another device"),this::joinDialog);add(content,t("Paired devices"),this::showDevices);add(content,t("My shared files"),()->{peer="";path="/";browse();});
            add(content,t("Import files into shared folder…"),()->{Intent picker=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE);picker.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true);startActivityForResult(picker,7);});add(content,t("Settings"),this::showSettings);}
        update(state.toString());
    }
    void showSettings(){screen="settings";content.removeAllViews();content.addView(label(t("Settings"),24));
        add(content,t("Storage and sharing"),this::showStorage);
        add(content,t("Device name")+": "+state.optString("name"),()->{EditText field=new EditText(this);field.setText(state.optString("name"));new AlertDialog.Builder(this).setTitle(t("Device name")).setView(field).setNegativeButton(android.R.string.cancel,null).setPositiveButton(android.R.string.ok,(d,w)->callState("set_name",field.getText().toString())).show();});
        add(content,t("Device role")+": "+state.optString("role"),()->new AlertDialog.Builder(this).setTitle(t("Device role")).setMessage(t("Allow this device to browse other paired devices too?"))
            .setNegativeButton(t("Controlled device"),(d,w)->callState("set_role","controlled")).setPositiveButton(t("Both directions"),(d,w)->callState("set_role","both")).show());
        add(content,t("Nearby devices"),this::showNearby);
        add(content,t("About"),()->new AlertDialog.Builder(this).setTitle("Soovee Commander 0.19.1").setMessage(t("Open source under MIT. Device storage is available after permission and sharing consent. CPython: PSF, Chaquopy: MIT, SPAKE2: MIT, qrcode: BSD-3-Clause, AndroidX: Apache-2.0.")).setPositiveButton(android.R.string.ok,null).show());
        add(content,t("Third-party licenses"),this::showLicenses);
        add(content,t("Diagnostic log"),()->worker.execute(()->{try{String text=core.callAttr("diagnostics").toString();runOnUiThread(()->new AlertDialog.Builder(this).setTitle(t("Diagnostic log")).setMessage(text).setPositiveButton(android.R.string.ok,null).setNeutralButton(t("Copy log"),(d,w)->((ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Soovee log",text))).show());}catch(Exception e){error(e);}}));
        if(!television)add(content,t("← Pairing and home"),this::showPairing);
    }
    void showLicenses(){try{
        ArrayList<String> files=new ArrayList<>();for(String name:getAssets().list(""))if(name.endsWith(".txt"))files.add(name);
        Collections.sort(files);new AlertDialog.Builder(this).setTitle(t("Third-party licenses")).setItems(files.toArray(new String[0]),(dialog,index)->{
            try(InputStream in=getAssets().open(files.get(index))){ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[4096];int n;while((n=in.read(buffer))!=-1)bytes.write(buffer,0,n);
                TextView text=label(bytes.toString("UTF-8"),16);text.setTextColor(0xff14233a);text.setTextIsSelectable(true);text.setPadding(dp(18),dp(8),dp(18),dp(8));ScrollView scroll=new ScrollView(this);scroll.addView(text);
                new AlertDialog.Builder(this).setTitle(files.get(index)).setView(scroll).setPositiveButton(android.R.string.ok,null).show();
            }catch(Exception e){error(e);}
        }).setNegativeButton(android.R.string.cancel,null).show();
    }catch(Exception e){error(e);}}
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);if(ready&&intent.getDataString()!=null)callState("pair",intent.getDataString(),"","0","");}
    void callState(String name,Object... args){HashSet<String> before=new HashSet<>();JSONArray peers=state.optJSONArray("peers");if(peers!=null)for(int i=0;i<peers.length();i++)before.add(peers.optJSONObject(i).optString("id"));worker.execute(()->{try{String value=core.callAttr(name,args).toString();runOnUiThread(()->{update(value);
        if(name.equals("pair")&&!television){JSONArray after=state.optJSONArray("peers");if(after!=null)for(int i=0;i<after.length();i++){String id=after.optJSONObject(i).optString("id");if(!before.contains(id)){peer=id;path="/";browse();return;}}showDevices();}
        else if(name.equals("set_name")||name.equals("set_role"))showSettings();else showHome();});}catch(Exception e){error(e);}});}
    void joinDialog(){LinearLayout form=column();form.setPadding(dp(18),dp(8),dp(18),dp(8));EditText invite=new EditText(this),host=new EditText(this),port=new EditText(this),pin=new EditText(this);
        invite.setHint(t("Paste Soovee invitation"));host.setHint(t("Local IP address"));port.setHint(t("Port"));pin.setHint(t("Eight-digit code"));port.setInputType(2);pin.setInputType(2);for(EditText field:new EditText[]{invite,host,port,pin})form.addView(field);
        new AlertDialog.Builder(this).setTitle(t("Pair device")).setView(form).setNegativeButton(android.R.string.cancel,null).setPositiveButton(t("Pair"),(d,w)->callState("pair",invite.getText().toString(),host.getText().toString(),port.getText().toString(),pin.getText().toString())).show();
    }
    void askCode(NetworkDiscovery.Device device,boolean asked){EditText pin=new EditText(this);pin.setHint(t("Eight-digit code"));pin.setInputType(2);
        AlertDialog.Builder dialog=new AlertDialog.Builder(this).setTitle(device.name).setMessage(t(asked?"The device now shows a pairing code. Type it here, or scan its QR.":"Open Soovee on the device and type the pairing code it shows, or scan its QR.")).setView(pin)
            .setNegativeButton(android.R.string.cancel,null).setPositiveButton(t("Pair"),(d,w)->callState("pair","",device.host,Integer.toString(device.port),pin.getText().toString()));
        if(!television)dialog.setNeutralButton(t("Scan QR instead"),(d,w)->scanner.launch(new com.journeyapps.barcodescanner.ScanOptions().setDesiredBarcodeFormats(com.journeyapps.barcodescanner.ScanOptions.QR_CODE).setBeepEnabled(false)));
        dialog.show();}
    void showPairingRequest(String name){showPairing();TextView who=label(String.format(t("%s wants to pair. Type this code there, or scan the QR."),name),television?24:18);who.setTextColor(CYAN);content.addView(who,1);}
    void showDevices(){screen="devices";content.removeAllViews();content.addView(label(t("Paired devices"),23));add(content,t("← Pairing and home"),this::showPairing);JSONArray devices=state.optJSONArray("peers");
        if(devices==null||devices.length()==0)content.addView(label(t("No paired devices yet."),18));
        else for(int i=0;i<devices.length();i++){JSONObject device=devices.optJSONObject(i);String id=device.optString("id");add(content,device.optString("name")+" · "+device.optString("host"),()->{if(state.optString("role").equals("controlled")){error(new Exception(t("Enable both directions in Device role first.")));return;}peer=id;path="/";browse();});
            add(content,t("Remove pairing")+" · "+device.optString("name"),()->new AlertDialog.Builder(this).setMessage(t("Remove this device’s access?")).setNegativeButton(android.R.string.cancel,null).setPositiveButton(android.R.string.ok,(d,w)->callState("remove_pairing",id)).show());}
    }
    void browse(){operationText=null;screen="files";String requestedPeer=peer,requestedPath=path;content.removeAllViews();content.addView(label(t("Loading files…"),18));worker.execute(()->{try{
        JSONArray entries=new JSONArray(requestedPeer.isEmpty()?core.callAttr("browse_local_path",requestedPath).toString():core.callAttr("browse",requestedPeer,requestedPath).toString());
        runOnUiThread(()->{if(isFinishing()||!screen.equals("files")||!peer.equals(requestedPeer)||!path.equals(requestedPath))return;content.removeAllViews();content.addView(new LibraryView(this,entries));});
    }catch(Exception e){error(e);}});}
    String selectedPath(JSONObject item){return (path.equals("/")?"/":path+"/")+item.optString("name");}
    void openLocal(String selected){worker.execute(()->{try{File file=new File(core.callAttr("local_file",selected).toString());runOnUiThread(()->openFile(file));}catch(Exception e){error(e);}});}
    void downloadFile(String selected){String sourcePeer=peer;new FolderPicker(this,core,worker,"",t("Save into"),this::t,destination->fileOperation(t("Copy"),()->core.callAttr("download_to",sourcePeer,selected,destination)),this::error);}
    interface FileTask {void run()throws Exception;}
    void fileOperation(String title,FileTask task){LinearLayout body=column();body.setPadding(dp(24),dp(12),dp(24),dp(12));ProgressBar progress=new ProgressBar(this);body.addView(progress);operationText=label(t("Working…"),16);body.addView(operationText);
        AlertDialog busy=new AlertDialog.Builder(this).setTitle(title).setView(body).setCancelable(false).setNegativeButton(t("Stop"),(d,w)->new Thread(()->{try{core.callAttr("cancel_operation");}catch(Exception e){error(e);}}).start()).create();busy.show();busy.getButton(-2).setOnClickListener(v->{busy.getButton(-2).setEnabled(false);new Thread(()->{try{core.callAttr("cancel_operation");}catch(Exception e){error(e);}}).start();});worker.execute(()->{try{task.run();String value=core.callAttr("snapshot").toString();runOnUiThread(()->{busy.dismiss();operationText=null;update(value);browse();Toast.makeText(this,t("Done"),Toast.LENGTH_SHORT).show();});}catch(Exception e){runOnUiThread(()->{busy.dismiss();operationText=null;});error(e);}});}
    void editFileName(JSONObject item,boolean create){if(path.equals("/")){error(new Exception(t("Choose a storage folder first.")));return;}String selected=create?path:selectedPath(item),sourcePeer=peer;
        EditText name=new EditText(this);name.setSingleLine(true);name.setText(create?"":item.optString("name"));name.selectAll();name.setPadding(dp(24),dp(12),dp(24),dp(12));
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle(t(create?"New folder":"Rename")).setMessage(selected).setView(name).setNegativeButton(android.R.string.cancel,null).setPositiveButton(t(create?"Create":"Rename"),null).create();
        dialog.setOnShowListener(v->dialog.getButton(-1).setOnClickListener(button->{String value=name.getText().toString();if(value.trim().isEmpty()||value.contains("/")||value.contains("\\")||value.equals(".")||value.equals("..")){name.setError(t("Enter a valid name."));return;}dialog.dismiss();browserSelection=value;fileOperation(t(create?"New folder":"Rename"),()->core.callAttr("mutate_item",sourcePeer,selected,create?"mkdir":"rename",value));}));dialog.show();}
    void confirmDelete(JSONObject item){if(path.equals("/"))return;String selected=selectedPath(item),sourcePeer=peer;
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle(t("Delete permanently?"))
            .setMessage(item.optString("name")+"\n\n"+selected+"\n\n"+t(item.optBoolean("directory")?"The folder and everything inside will be deleted. This does not use the Trash.":"This file will be permanently deleted. This does not use the Trash."))
            .setNegativeButton(t("Keep file"),null).setPositiveButton(t("Delete"),(d,w)->fileOperation(t("Delete"),()->core.callAttr("mutate_item",sourcePeer,selected,"remove",""))).create();dialog.setOnShowListener(v->{dialog.getButton(-1).setTextColor(0xffff7587);dialog.getButton(-2).requestFocus();});dialog.show();}
    void copyLocal(JSONObject item,boolean moving){if(!peer.isEmpty()||path.equals("/"))return;String selected=selectedPath(item);
        new FolderPicker(this,core,worker,"",t(moving?"Move into":"Copy into"),this::t,destination->{new AlertDialog.Builder(this).setTitle(t(moving?"Move":"Copy")).setMessage(selected+"\n↓\n"+destination).setNegativeButton(android.R.string.cancel,null).setPositiveButton(t(moving?"Move":"Copy"),(d,w)->fileOperation(t(moving?"Move":"Copy"),()->core.callAttr("copy_local_item",selected,destination,moving))).show();},this::error);}
    void chooseUpload(){try{uploadPeer=peer;uploadPath=path;Intent picker=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE);picker.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true);startActivityForResult(picker,7);}catch(Exception e){uploadPeer="";uploadPath="";error(e);}}
    void parentFolder(){int slash=path.lastIndexOf('/');browserSelection=path.substring(slash+1);path=slash<=0?"/":path.substring(0,slash);browse();}
    String storageState()throws Exception{return core.callAttr("configure_storage",DeviceStorage.roots(this).toString(),getSharedPreferences("soovee",0).getBoolean("share_storage",false)&&DeviceStorage.permitted(this)).toString();}
    void refreshStorage(){if(!ready)return;worker.execute(()->{try{String value=storageState();runOnUiThread(()->{update(value);if(screen.equals("storage"))showStorage();});}catch(Exception e){error(e);}});}
    @Override protected void onResume(){super.onResume();refreshStorage();}
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results){super.onRequestPermissionsResult(request,permissions,results);if(request==17)refreshStorage();}
    String storageCaption(JSONObject volume){return volume.optString("path")+"\n"+t("Free")+" "+android.text.format.Formatter.formatFileSize(this,volume.optLong("free"))+" · "+t("Total")+" "+android.text.format.Formatter.formatFileSize(this,volume.optLong("total"))+"\n"+t(volume.optBoolean("shared")?"Available to approved paired devices":"Only on this device");}
    void showStorage(){screen="storage";content.removeAllViews();storageLabels.clear();content.addView(label(t("Storage and files"),25));
        if(television){showTvStorage();return;}
        content.addView(label(t("Choose a storage to browse. Its real location and available space are shown below."),16));
        JSONArray volumes=state.optJSONArray("storage");if(volumes!=null)for(int i=0;i<volumes.length();i++){JSONObject volume=volumes.optJSONObject(i);String name=volume.optString("name");
            add(content,t(name),()->{peer="";path="/"+name;browse();});TextView details=label(storageCaption(volume),15);details.setTextIsSelectable(true);storageLabels.put(volume.optString("key"),details);content.addView(details);
        }
        if(state.optBoolean("storageSharing"))add(content,t("Stop sharing device storage"),()->new AlertDialog.Builder(this).setTitle(t("Stop sharing device storage")).setMessage(t("Paired devices will keep access to the app Shared folder only.")).setNegativeButton(android.R.string.cancel,null).setPositiveButton(android.R.string.ok,(d,w)->{getSharedPreferences("soovee",0).edit().putBoolean("share_storage",false).apply();refreshStorage();}).show());
        else add(content,t("Allow access to device storage…"),this::allowStorage);
        content.addView(label(t("Android protects other apps’ private data. Internal shared storage and supported USB drives can be made available after permission is granted."),15));
        if(!television){add(content,t("Import a file…"),()->{uploadPeer="";uploadPath="";try{startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE),7);}catch(Exception e){error(e);}});add(content,t("Nearby devices"),this::showNearby);}
    }
    void showTvStorage(){content.addView(label(t("Choose a storage. Open it to manage its files."),16));
        JSONArray volumes=state.optJSONArray("storage");LinearLayout row=null;
        if(volumes!=null)for(int i=0;i<volumes.length();i++){JSONObject volume=volumes.optJSONObject(i);String name=volume.optString("name");
            if(i%2==0){row=new LinearLayout(this);content.addView(row);}
            LinearLayout card=column();card.setPadding(dp(18),dp(14),dp(18),dp(14));card.setBackground(shape(SURFACE,0xff2d4260));
            TextView heading=label("▰  "+t(name),21);heading.setTypeface(null,Typeface.BOLD);heading.setTextColor(CYAN);card.addView(heading);
            TextView free=label(t("Free")+" "+android.text.format.Formatter.formatFileSize(this,volume.optLong("free")),19);card.addView(free);
            ProgressBar capacity=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);capacity.setMax(1000);long total=volume.optLong("total");capacity.setProgress(total>0?(int)(1000.0*(total-volume.optLong("free"))/total):0);capacity.setProgressTintList(android.content.res.ColorStateList.valueOf(CYAN));card.addView(capacity,new LinearLayout.LayoutParams(-1,dp(5)));
            TextView details=label(t("Total")+" "+android.text.format.Formatter.formatFileSize(this,total)+"\n"+volume.optString("path"),12);details.setTextColor(0xffa9b9cf);details.setMaxLines(3);details.setEllipsize(android.text.TextUtils.TruncateAt.MIDDLE);card.addView(details);
            TextView sharing=label(t(volume.optBoolean("shared")?"Shared with paired devices":"Only on this device"),12);sharing.setTextColor(volume.optBoolean("shared")?CYAN:0xffa9b9cf);card.addView(sharing);
            Button open=button(t("Open storage"),()->{peer="";path="/"+name;browserSelection="";browse();});open.setTextSize(15);open.setMinHeight(dp(40));card.addView(open,new LinearLayout.LayoutParams(-1,dp(44)));
            LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,-2,1);p.setMargins(0,dp(10),dp(12),dp(8));row.addView(card,p);
        }
        if(volumes!=null&&volumes.length()%2==1)row.addView(new Space(this),new LinearLayout.LayoutParams(0,1,1));
        if(!state.optBoolean("storageSharing"))add(content,t("Allow access to device storage…"),this::allowStorage);
        else add(content,t("Stop sharing device storage"),()->new AlertDialog.Builder(this).setTitle(t("Stop sharing device storage")).setMessage(t("Paired devices will keep access to the app Shared folder only.")).setNegativeButton(android.R.string.cancel,null).setPositiveButton(android.R.string.ok,(d,w)->{getSharedPreferences("soovee",0).edit().putBoolean("share_storage",false).apply();refreshStorage();}).show());
    }
    void allowStorage(){new AlertDialog.Builder(this).setTitle(t("Share device storage"))
        .setMessage(t("Allow approved paired devices to browse and copy files in internal shared storage and connected USB drives? Other apps’ private data stays protected. Android will ask for storage permission."))
        .setNegativeButton(android.R.string.cancel,null).setPositiveButton(t("Continue"),(d,w)->{
            getSharedPreferences("soovee",0).edit().putBoolean("share_storage",true).apply();
            if(DeviceStorage.permitted(this)){refreshStorage();return;}
            try{if(Build.VERSION.SDK_INT>=30){Intent settings=new Intent(android.provider.Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,Uri.parse("package:"+getPackageName()));
                try{startActivity(settings);}catch(ActivityNotFoundException missing){startActivity(new Intent(android.provider.Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));}}
                else requestPermissions(new String[]{android.Manifest.permission.READ_EXTERNAL_STORAGE,android.Manifest.permission.WRITE_EXTERNAL_STORAGE},17);
            }catch(Exception e){error(e);}
        }).show();}
    boolean paired(String identity){JSONArray values=state.optJSONArray("peers");if(values!=null)for(int i=0;i<values.length();i++)if(values.optJSONObject(i).optString("id").equals(identity))return true;return false;}
    void showNearby(){screen="nearby";content.removeAllViews();content.addView(label(t("Nearby devices"),25));content.addView(label(t("Choose a device and enter its code. No IP address is needed."),16));
        if(!television)add(content,t("Scan pairing QR"),()->scanner.launch(new com.journeyapps.barcodescanner.ScanOptions().setDesiredBarcodeFormats(com.journeyapps.barcodescanner.ScanOptions.QR_CODE).setBeepEnabled(false).setOrientationLocked(false).setPrompt(t("Scan pairing QR"))));
        List<NetworkDiscovery.Device> values=network==null?Collections.emptyList():network.snapshot();
        if(values.isEmpty())content.addView(label(t("Looking for Soovee devices on your network…"),17));
        for(NetworkDiscovery.Device device:values)add(content,device.name+" · "+t(paired(device.id)?"Paired · open":"Tap to pair"),()->{
            if(paired(device.id)){if(state.optString("role").equals("controlled")){error(new Exception(t("Enable both directions in Device role first.")));return;}
                worker.execute(()->{try{String value=core.callAttr("reconnect",device.id,device.host,device.port).toString();runOnUiThread(()->{update(value);peer=device.id;path="/";browse();});}catch(Exception e){error(e);}});
            }else worker.execute(()->{boolean asked=false;  // The device shows its code itself; then type or scan it here.
                try{asked=new JSONObject(core.callAttr("request_pairing",device.host,device.port).toString()).optBoolean("asked");}catch(Exception ignored){}
                final boolean shown=asked;runOnUiThread(()->askCode(device,shown));});
        });
        add(content,t("My QR and pairing code"),this::showPairing);add(content,t("Storage and files"),this::showStorage);add(content,t("Paired devices"),this::showDevices);
        add(content,t("Connect by address…"),this::joinDialog);if(!television)add(content,t("Settings"),this::showSettings);
    }
    void localFileMenu(String selected,String name){ArrayList<String> options=new ArrayList<>(Arrays.asList(t("Open"),t("Delete")));if(!state.optString("role").equals("controlled"))options.add(t("Copy to a device…"));
        new AlertDialog.Builder(this).setTitle(name).setItems(options.toArray(new String[0]),(d,which)->{
            if(which==0)worker.execute(()->{try{File file=new File(core.callAttr("local_file",selected).toString());runOnUiThread(()->openFile(file));}catch(Exception e){error(e);}});
            else if(which==1)new AlertDialog.Builder(this).setTitle(name).setMessage(t("Delete this item?")).setNegativeButton(android.R.string.cancel,null).setPositiveButton(t("Delete"),(a,w)->worker.execute(()->{try{core.callAttr("delete_local_path",selected);runOnUiThread(this::browse);}catch(Exception e){error(e);}})).show();
            else{JSONArray devices=state.optJSONArray("peers");if(devices==null||devices.length()==0){showNearby();return;}String[] names=new String[devices.length()];for(int i=0;i<names.length;i++)names[i]=devices.optJSONObject(i).optString("name");
                new AlertDialog.Builder(this).setTitle(t("Choose a device")).setItems(names,(box,index)->{String target=devices.optJSONObject(index).optString("id");new FolderPicker(this,core,worker,target,t("Copy into"),this::t,destination->worker.execute(()->{try{core.callAttr("upload_from",target,destination,selected);runOnUiThread(()->Toast.makeText(this,t("File copied")+" · "+destination,Toast.LENGTH_LONG).show());}catch(Exception e){error(e);}}),this::error);}).setNegativeButton(android.R.string.cancel,null).show();}
        }).show();}
    void openFile(File file){try{Uri uri=FileProvider.getUriForFile(this,getPackageName()+".files",file);String type=android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(android.webkit.MimeTypeMap.getFileExtensionFromUrl(file.getName()).toLowerCase(Locale.ROOT));startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(uri,type==null?"application/octet-stream":type).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));}catch(Exception e){error(e);}}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request!=7||result!=RESULT_OK||data==null)return;ArrayList<Uri> values=new ArrayList<>();if(data.getClipData()!=null)for(int i=0;i<data.getClipData().getItemCount();i++)values.add(data.getClipData().getItemAt(i).getUri());else if(data.getData()!=null)values.add(data.getData());
        String targetPeer=uploadPeer,targetPath=uploadPath;uploadPeer="";uploadPath="";
        worker.execute(()->{try{for(Uri uri:values){String name="imported-file";try(Cursor cursor=getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)){if(cursor!=null&&cursor.moveToFirst())name=cursor.getString(0);}try(ParcelFileDescriptor fd=getContentResolver().openFileDescriptor(uri,"r")){core.callAttr("import_file",name,fd.getFd());}if(!targetPeer.isEmpty())core.callAttr("upload_from",targetPeer,targetPath,"/Shared/"+name);}runOnUiThread(()->{if(targetPeer.isEmpty()){peer="";path="/Shared";}browse();});}catch(Exception e){error(e);}});
    }
    /** Python workers call this; every pairing explicitly grants only the Shared folder. */
    public boolean approve(String kind,String payload){CountDownLatch done=new CountDownLatch(1);AtomicBoolean accepted=new AtomicBoolean(false);runOnUiThread(()->{if(isFinishing()){done.countDown();return;}try{JSONObject request=new JSONObject(payload);
        String message=kind.equals("pair")?t("Confirm pairing with this device:")+"\n"+request.optString("name")+"\n"+request.optString("host")+"\n"+t("Verification:")+" "+request.optString("verification")+"\n\n"+t(request.optBoolean("storageSharing")?"Allow this device to browse and copy files in the shared device storage? Other apps’ private files remain protected.":"Allow this device to browse and upload to this app’s Shared folder? Other folders are not shared.")
            :t("Receive files from this device?")+"\n"+request.optString("name")+" · "+request.optInt("files")+" · "+request.optLong("bytes")+" B";
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle(t("Confirm device access")).setMessage(message).setNegativeButton(android.R.string.cancel,(d,w)->done.countDown()).setPositiveButton(t("Allow"),(d,w)->{accepted.set(true);done.countDown();}).create();dialog.setOnDismissListener(d->{approvals.remove(dialog);done.countDown();});approvals.add(dialog);dialog.show();dialog.getButton(-2).requestFocus();timer.postDelayed(()->{if(dialog.isShowing())dialog.dismiss();},120000);
    }catch(Exception e){done.countDown();error(e);}});try{if(!done.await(120,TimeUnit.SECONDS))return false;}catch(InterruptedException e){Thread.currentThread().interrupt();return false;}return accepted.get();}
    public void activity(String payload){runOnUiThread(()->{if(!isFinishing())try{JSONObject event=new JSONObject(payload);
        if(event.optString("kind").equals("pair-request")){showPairingRequest(event.optString("name"));return;}
        if(event.optString("kind").equals("paired"))worker.execute(()->{try{String value=core.callAttr("snapshot").toString();runOnUiThread(()->update(value));}catch(Exception ignored){}});String message=event.optString("message",event.optString("name",event.optString("path")));status.setText(event.optString("kind")+" · "+message);if(operationText!=null)operationText.setText(event.optString("current",message)+"\n"+android.text.format.Formatter.formatFileSize(this,event.optLong("bytes"))+" · "+event.optInt("completed")+" / "+event.optInt("files"));}catch(Exception ignored){}});}
    void error(Exception e){String original=e.getMessage()==null?e.getClass().getSimpleName():e.getMessage();if(core!=null&&!worker.isShutdown())worker.execute(()->{try{core.callAttr("record_error",original);}catch(Exception ignored){}});
        String message=original.split("\n",2)[0].replaceFirst("^(?:TransferError|ValueError|PermissionError|FileExistsError|FileNotFoundError|OSError):\\s*","");
        runOnUiThread(()->{if(!isFinishing())new AlertDialog.Builder(this).setTitle(t("Soovee · Error")).setMessage(t(message)).setPositiveButton(android.R.string.ok,null).show();});}
    @Override public void onBackPressed(){if(!screen.equals("home")){if(screen.equals("files")&&!path.equals("/"))parentFolder();else showHome();}else super.onBackPressed();}
    @Override protected void onDestroy(){ready=false;timer.removeCallbacksAndMessages(null);if(network!=null)network.close();for(AlertDialog dialog:new ArrayList<>(approvals))dialog.dismiss();if(core!=null)worker.execute(()->core.callAttr("stop",this));worker.shutdown();super.onDestroy();}
}
