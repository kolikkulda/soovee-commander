package cz.soovee.commander;

import android.content.Context;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import java.net.Inet4Address;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Bonjour hints only: every connection still requires code pairing or its saved PSK. */
final class NetworkDiscovery implements AutoCloseable {
    static final String TYPE = "_soovee._tcp.";
    static final class Device {
        final String id,name,host,kind; final int port;
        Device(String id,String name,String host,int port,String kind){this.id=id;this.name=name;this.host=host;this.port=port;this.kind=kind;}
        String signature(){return id+"\n"+name+"\n"+host+":"+port+"\n"+kind;}
    }
    final NsdManager manager; final Runnable changed;
    final String identity,name; final int port;
    final Map<String,Device> devices=new HashMap<>();
    final Map<String,String> serviceIds=new HashMap<>();
    final Set<String> active=new HashSet<>(), queued=new HashSet<>();
    final ArrayDeque<NsdServiceInfo> pending=new ArrayDeque<>();
    boolean closed=false,resolving=false;
    NsdManager.RegistrationListener registration;
    NsdManager.DiscoveryListener browser;

    NetworkDiscovery(Context context,String identity,String name,int port,String kind,Runnable changed){
        this.manager=(NsdManager)context.getSystemService(Context.NSD_SERVICE);this.identity=identity;this.name=name;this.port=port;this.changed=changed;
        NsdServiceInfo info=new NsdServiceInfo();info.setServiceType(TYPE);info.setServiceName("soovee-"+identity);info.setPort(port);
        String advertised=name;while(advertised.getBytes(StandardCharsets.UTF_8).length>240)advertised=advertised.substring(0,advertised.offsetByCodePoints(0,advertised.codePointCount(0,advertised.length())-1));
        info.setAttribute("v","1");info.setAttribute("id",identity);info.setAttribute("name",advertised);info.setAttribute("kind",kind);
        registration=new NsdManager.RegistrationListener(){
            public void onServiceRegistered(NsdServiceInfo service){if(closed)try{manager.unregisterService(this);}catch(Exception ignored){}}
            public void onRegistrationFailed(NsdServiceInfo service,int code){android.util.Log.w("SooveeCommander","Discovery registration failed: "+code);}
            public void onServiceUnregistered(NsdServiceInfo service){}
            public void onUnregistrationFailed(NsdServiceInfo service,int code){}
        };
        browser=new NsdManager.DiscoveryListener(){
            public void onDiscoveryStarted(String type){if(closed)try{manager.stopServiceDiscovery(this);}catch(Exception ignored){}}
            public void onDiscoveryStopped(String type){}
            public void onStartDiscoveryFailed(String type,int code){android.util.Log.w("SooveeCommander","Discovery unavailable: "+code);}
            public void onStopDiscoveryFailed(String type,int code){}
            public void onServiceFound(NsdServiceInfo service){synchronized(NetworkDiscovery.this){
                if(closed||!service.getServiceType().startsWith("_soovee._tcp")||active.size()>=256)return;
                String key=service.getServiceName();active.add(key);
                if(queued.add(key)){pending.add(service);resolveNext();}
            }}
            public void onServiceLost(NsdServiceInfo service){synchronized(NetworkDiscovery.this){
                String key=service.getServiceName();active.remove(key);String id=serviceIds.remove(key);
                if(id!=null&&devices.remove(id)!=null)changed.run();
            }}
        };
        try{manager.registerService(info,NsdManager.PROTOCOL_DNS_SD,registration);manager.discoverServices(TYPE,NsdManager.PROTOCOL_DNS_SD,browser);}
        catch(Exception error){android.util.Log.w("SooveeCommander","Local discovery could not start");}
    }

    synchronized List<Device> snapshot(){ArrayList<Device> result=new ArrayList<>(devices.values());result.sort(Comparator.comparing(v->v.name.toLowerCase(Locale.ROOT)));return result;}
    static String text(Map<String,byte[]> attributes,String key){byte[] value=attributes.get(key);return value==null||value.length>320?"":new String(value,StandardCharsets.UTF_8);}

    @SuppressWarnings("deprecation") synchronized void resolveNext(){
        if(closed||resolving||pending.isEmpty())return;
        NsdServiceInfo service=pending.remove();resolving=true;
        manager.resolveService(service,new NsdManager.ResolveListener(){
            public void onResolveFailed(NsdServiceInfo info,int code){finish();}
            public void onServiceResolved(NsdServiceInfo info){synchronized(NetworkDiscovery.this){
                try{
                    String id=text(info.getAttributes(),"id"),name=text(info.getAttributes(),"name"),kind=text(info.getAttributes(),"kind");
                    if(!closed&&active.contains(service.getServiceName())&&text(info.getAttributes(),"v").equals("1")&&id.matches("[a-f0-9]{32}")&&!id.equals(identity)&&!name.isEmpty()&&name.length()<=80&&!name.matches("(?s).*[\\x00-\\x1f].*")&&info.getHost() instanceof Inet4Address&&info.getHost().isSiteLocalAddress()&&info.getPort()>0&&info.getPort()<=65535){
                        if(!Arrays.asList("tv","phone","desktop").contains(kind))kind="desktop";
                        Device value=new Device(id,name,info.getHost().getHostAddress(),info.getPort(),kind),old=devices.put(id,value);
                        serviceIds.put(service.getServiceName(),id);
                        if(old==null||!old.signature().equals(value.signature()))changed.run();
                    }
                }finally{finish();}
            }}
            void finish(){synchronized(NetworkDiscovery.this){queued.remove(service.getServiceName());resolving=false;resolveNext();}}
        });
    }

    @Override public synchronized void close(){
        if(closed)return;closed=true;pending.clear();devices.clear();
        try{manager.stopServiceDiscovery(browser);}catch(Exception ignored){}
        try{manager.unregisterService(registration);}catch(Exception ignored){}
    }
}
