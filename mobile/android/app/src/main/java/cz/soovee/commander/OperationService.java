package cz.soovee.commander;

import android.app.*;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

/** Keeps the app alive while a copy, move or archive runs, with its progress in a notification. */
public final class OperationService extends Service {
    static final String CHANNEL="operations";static final int ID=41;
    static void start(Context context,String title){
        Intent intent=new Intent(context,OperationService.class).putExtra("title",title);
        try{if(Build.VERSION.SDK_INT>=26)context.startForegroundService(intent);else context.startService(intent);}catch(Exception ignored){}
    }
    static void stop(Context context){context.stopService(new Intent(context,OperationService.class));}
    static void progress(Context context,String title,String text,int percent){
        NotificationManager manager=context.getSystemService(NotificationManager.class);if(manager==null)return;
        try{manager.notify(ID,build(context,title,text,percent));}catch(Exception ignored){}
    }
    static Notification build(Context context,String title,String text,int percent){
        NotificationManager manager=context.getSystemService(NotificationManager.class);
        if(Build.VERSION.SDK_INT>=26&&manager!=null&&manager.getNotificationChannel(CHANNEL)==null)
            manager.createNotificationChannel(new NotificationChannel(CHANNEL,"Transfers",NotificationManager.IMPORTANCE_LOW));
        Notification.Builder b=Build.VERSION.SDK_INT>=26?new Notification.Builder(context,CHANNEL):new Notification.Builder(context);
        PendingIntent open=PendingIntent.getActivity(context,0,new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_IMMUTABLE);
        b.setSmallIcon(android.R.drawable.stat_sys_download).setContentTitle(title).setContentText(text).setOngoing(true).setOnlyAlertOnce(true).setContentIntent(open);
        if(percent>=0)b.setProgress(100,percent,false);else b.setProgress(0,0,true);
        return b.build();
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        Notification n=build(this,intent==null?"Soovee Commander":intent.getStringExtra("title"),"",-1);
        try{if(Build.VERSION.SDK_INT>=29)startForeground(ID,n,ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);else startForeground(ID,n);}catch(Exception e){stopSelf();}
        return START_NOT_STICKY;
    }
    @Override public void onDestroy(){if(Build.VERSION.SDK_INT>=24)stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy();}
    @Override public IBinder onBind(Intent intent){return null;}
}
