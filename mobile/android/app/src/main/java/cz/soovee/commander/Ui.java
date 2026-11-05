package cz.soovee.commander;

import android.app.Dialog;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.*;
import android.graphics.drawable.*;
import android.text.TextUtils;
import android.view.*;
import android.widget.*;
import androidx.core.graphics.PathParser;
import java.util.HashMap;
import java.util.Map;

/** Shared look for phone and TV: light/dark colors, vector icons, grouped sections and rows. */
final class Ui {
    final MainActivity a;
    final boolean dark, tv;
    final int bg, surface, raised, text, secondary, tertiary, separator, accent, onAccent, danger, focus;
    Ui(MainActivity activity){
        a=activity;tv=activity.television;
        int choice=activity.getSharedPreferences("soovee",0).getInt("appearance",0);   // 0 system, 1 light, 2 dark
        boolean system=(activity.getResources().getConfiguration().uiMode&Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES;
        dark=tv||choice==2||(choice==0&&system);
        bg=dark?0xff0b1020:0xfff2f4f8;surface=dark?0xff151d31:0xffffffff;raised=dark?0xff1d2740:0xffe8ecf3;
        text=dark?0xfff5f7fb:0xff101828;secondary=dark?0xff9aa6bf:0xff5d6678;tertiary=dark?0xff69748c:0xff98a1b3;
        separator=dark?0x26ffffff:0x1f000000;accent=dark?0xff1adce6:0xff0b8f9c;onAccent=dark?0xff06121c:0xffffffff;danger=dark?0xffff6b7d:0xffd92d42;focus=dark?0x3a1adce6:0x2a0b8f9c;
    }
    int dp(float value){return Math.round(value*a.getResources().getDisplayMetrics().density);}
    String t(String s){return a.t(s);}

    // ---------- icons (Material icon outlines, 24×24 path data) ----------
    static final Map<String,String> PATHS=new HashMap<>();
    static {
        PATHS.put("home","M10,20v-6h4v6h5v-8h3L12,3 2,12h3v8z");
        PATHS.put("folder","M10,4H4c-1.1,0 -1.99,0.9 -1.99,2L2,18c0,1.1 0.9,2 2,2h16c1.1,0 2,-0.9 2,-2V8c0,-1.1 -0.9,-2 -2,-2h-8l-2,-2z");
        PATHS.put("devices","M4,6h18V4H4c-1.1,0 -2,0.9 -2,2v11H0v3h14v-3H4V6zM23,8h-6c-0.55,0 -1,0.45 -1,1v10c0,0.55 0.45,1 1,1h6c0.55,0 1,-0.45 1,-1V9c0,-0.55 -0.45,-1 -1,-1zM22,17h-4v-7h4v7z");
        PATHS.put("swap","M6.99,11L3,15l3.99,4v-3H14v-2H6.99v-3zM21,9l-3.99,-4v3H10v2h7.01v3L21,9z");
        PATHS.put("search","M15.5,14h-0.79l-0.28,-0.27C15.41,12.59 16,11.11 16,9.5 16,5.91 13.09,3 9.5,3S3,5.91 3,9.5 5.91,16 9.5,16c1.61,0 3.09,-0.59 4.23,-1.57l0.27,0.28v0.79l5,4.99L20.49,19l-4.99,-5zM9.5,14C7.01,14 5,11.99 5,9.5S7.01,5 9.5,5 14,7.01 14,9.5 11.99,14 9.5,14z");
        PATHS.put("more","M12,8c1.1,0 2,-0.9 2,-2s-0.9,-2 -2,-2 -2,0.9 -2,2 0.9,2 2,2zM12,10c-1.1,0 -2,0.9 -2,2s0.9,2 2,2 2,-0.9 2,-2 -0.9,-2 -2,-2zM12,16c-1.1,0 -2,0.9 -2,2s0.9,2 2,2 2,-0.9 2,-2 -0.9,-2 -2,-2z");
        PATHS.put("back","M20,11H7.83l5.59,-5.59L12,4l-8,8 8,8 1.41,-1.41L7.83,13H20v-2z");
        PATHS.put("chevron","M10,6L8.59,7.41 13.17,12l-4.58,4.59L10,18l6,-6z");
        PATHS.put("check","M12,2C6.48,2 2,6.48 2,12s4.48,10 10,10 10,-4.48 10,-10S17.52,2 12,2zM10,17l-5,-5 1.41,-1.41L10,14.17l7.59,-7.59L19,8l-9,9z");
        PATHS.put("circle","M12,2C6.47,2 2,6.47 2,12s4.47,10 10,10 10,-4.47 10,-10S17.53,2 12,2zM12,20c-4.42,0 -8,-3.58 -8,-8s3.58,-8 8,-8 8,3.58 8,8 -3.58,8 -8,8z");
        PATHS.put("sort","M3,18h6v-2H3v2zM3,6v2h18V6H3zM3,13h12v-2H3v2z");
        PATHS.put("file","M6,2c-1.1,0 -1.99,0.9 -1.99,2L4,20c0,1.1 0.89,2 1.99,2H18c1.1,0 2,-0.9 2,-2V8l-6,-6H6zM13,9V3.5L18.5,9H13z");
        PATHS.put("image","M21,19V5c0,-1.1 -0.9,-2 -2,-2H5c-1.1,0 -2,0.9 -2,2v14c0,1.1 0.9,2 2,2h14c1.1,0 2,-0.9 2,-2zM8.5,13.5l2.5,3.01L14.5,12l4.5,6H5l3.5,-4.5z");
        PATHS.put("movie","M18,4l2,4h-3l-2,-4h-2l2,4h-3l-2,-4H8l2,4H7L5,4H4c-1.1,0 -1.99,0.9 -1.99,2L2,18c0,1.1 0.9,2 2,2h16c1.1,0 2,-0.9 2,-2V4h-4z");
        PATHS.put("music","M12,3v10.55c-0.59,-0.34 -1.27,-0.55 -2,-0.55 -2.21,0 -4,1.79 -4,4s1.79,4 4,4 4,-1.79 4,-4V7h4V3h-6z");
        PATHS.put("archive","M20.54,5.23l-1.39,-1.68C18.88,3.21 18.47,3 18,3H6c-0.47,0 -0.88,0.21 -1.16,0.55L3.46,5.23C3.17,5.57 3,6.02 3,6.5V19c0,1.1 0.9,2 2,2h14c1.1,0 2,-0.9 2,-2V6.5c0,-0.48 -0.17,-0.93 -0.46,-1.27zM12,17.5L6.5,12H10v-2h4v2h3.5L12,17.5zM5.12,5l0.81,-1h12l0.94,1H5.12z");
        PATHS.put("settings","M3,17v2h6v-2H3zM3,5v2h10V5H3zM13,21v-2h8v-2h-8v-2h-2v6h2zM7,9v2H3v2h4v2h2V9H7zM21,13v-2H11v2h10zM15,9h2V7h4V5h-4V3h-2v6z");
        PATHS.put("delete","M6,19c0,1.1 0.9,2 2,2h8c1.1,0 2,-0.9 2,-2V7H6v12zM19,4h-3.5l-1,-1h-5l-1,1H5v2h14V4z");
        PATHS.put("share","M18,16.08c-0.76,0 -1.44,0.3 -1.96,0.77L8.91,12.7c0.05,-0.23 0.09,-0.46 0.09,-0.7s-0.04,-0.47 -0.09,-0.7l7.05,-4.11c0.54,0.5 1.25,0.81 2.04,0.81 1.66,0 3,-1.34 3,-3s-1.34,-3 -3,-3 -3,1.34 -3,3c0,0.24 0.04,0.47 0.09,0.7L8.04,9.81C7.5,9.31 6.79,9 6,9c-1.66,0 -3,1.34 -3,3s1.34,3 3,3c0.79,0 1.5,-0.31 2.04,-0.81l7.12,4.16c-0.05,0.21 -0.08,0.43 -0.08,0.65 0,1.61 1.31,2.92 2.92,2.92 1.61,0 2.92,-1.31 2.92,-2.92s-1.31,-2.92 -2.92,-2.92z");
        PATHS.put("copy","M16,1H4c-1.1,0 -2,0.9 -2,2v14h2V3h12V1zM19,5H8c-1.1,0 -2,0.9 -2,2v14c0,1.1 0.9,2 2,2h11c1.1,0 2,-0.9 2,-2V7c0,-1.1 -0.9,-2 -2,-2zM19,21H8V7h11v14z");
        PATHS.put("close","M19,6.41L17.59,5 12,10.59 6.41,5 5,6.41 10.59,12 5,17.59 6.41,19 12,13.41 17.59,19 19,17.59 13.41,12z");
        PATHS.put("add","M19,13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z");
        PATHS.put("qr","M9.5,6.5v3h-3v-3h3M11,5H5v6h6V5zM9.5,14.5v3h-3v-3h3M11,13H5v6h6v-6zM17.5,6.5v3h-3v-3h3M19,5h-6v6h6V5zM13,13h1.5v1.5H13zM14.5,14.5H16V16h-1.5zM16,13h1.5v1.5H16zM13,16h1.5v1.5H13zM14.5,17.5H16V19h-1.5zM16,16h1.5v1.5H16zM17.5,14.5H19V16h-1.5zM17.5,17.5H19V19h-1.5zM22,7h-2V4h-3V2h5v5zM22,22v-5h-2v3h-3v2h5zM2,22h5v-2H4v-3H2v5zM2,2v5h2V4h3V2H2z");
        PATHS.put("tv","M21,3H3c-1.1,0 -2,0.9 -2,2v12c0,1.1 0.9,2 2,2h5v2h8v-2h5c1.1,0 1.99,-0.9 1.99,-2L23,5c0,-1.1 -0.9,-2 -2,-2zM21,17H3V5h18v12z");
        PATHS.put("phone","M17,1.01L7,1c-1.1,0 -2,0.9 -2,2v18c0,1.1 0.9,2 2,2h10c1.1,0 2,-0.9 2,-2V3c0,-1.1 -0.9,-1.99 -2,-1.99zM17,19H7V5h10v14z");
        PATHS.put("computer","M20,18c1.1,0 1.99,-0.9 1.99,-2L22,6c0,-1.1 -0.9,-2 -2,-2H4c-1.1,0 -2,0.9 -2,2v10c0,1.1 0.9,2 2,2H0v2h24v-2h-4zM4,6h16v10H4V6z");
        PATHS.put("storage","M2,20h20v-4H2v4zM4,17h2v2H4v-2zM2,4v4h20V4H2zM6,7H4V5h2v2zM2,14h20v-4H2v4zM4,11h2v2H4v-2z");
        PATHS.put("star","M12,17.27L18.18,21l-1.64,-7.03L22,9.24l-7.19,-0.61L12,2 9.19,8.63 2,9.24l5.46,4.73L5.82,21z");
        PATHS.put("history","M13,3c-4.97,0 -9,4.03 -9,9H1l3.89,3.89 0.07,0.14L9,12H6c0,-3.87 3.13,-7 7,-7s7,3.13 7,7 -3.13,7 -7,7c-1.93,0 -3.68,-0.79 -4.94,-2.06l-1.42,1.42C8.27,19.99 10.51,21 13,21c4.97,0 9,-4.03 9,-9s-4.03,-9 -9,-9zM12,8v5l4.28,2.54 0.72,-1.21 -3.5,-2.08V8H12z");
        PATHS.put("info","M12,2C6.48,2 2,6.48 2,12s4.48,10 10,10 10,-4.48 10,-10S17.52,2 12,2zM13,17h-2v-6h2v6zM13,9h-2V7h2v2z");
        PATHS.put("edit","M3,17.25V21h3.75L17.81,9.94l-3.75,-3.75L3,17.25zM20.71,7.04c0.39,-0.39 0.39,-1.02 0,-1.41l-2.34,-2.34c-0.39,-0.39 -1.02,-0.39 -1.41,0l-1.83,1.83 3.75,3.75 1.83,-1.83z");
        PATHS.put("grid","M4,11h5V5H4v6zM4,18h5v-6H4v6zM10,18h5v-6h-5v6zM16,18h5v-6h-5v6zM10,11h5V5h-5v6zM16,5v6h5V5h-5z");
        PATHS.put("list","M3,13h2v-2H3v2zM3,17h2v-2H3v2zM3,9h2V7H3v2zM7,13h14v-2H7v2zM7,17h14v-2H7v2zM7,7v2h14V7H7z");
        PATHS.put("link","M3.9,12c0,-1.71 1.39,-3.1 3.1,-3.1h4V7H7c-2.76,0 -5,2.24 -5,5s2.24,5 5,5h4v-1.9H7c-1.71,0 -3.1,-1.39 -3.1,-3.1zM8,13h8v-2H8v2zM17,7h-4v1.9h4c1.71,0 3.1,1.39 3.1,3.1s-1.39,3.1 -3.1,3.1h-4V17h4c2.76,0 5,-2.24 5,-5s-2.24,-5 -5,-5z");
        PATHS.put("download","M19,9h-4V3H9v6H5l7,7 7,-7zM5,18v2h14v-2H5z");
        PATHS.put("refresh","M17.65,6.35C16.2,4.9 14.21,4 12,4c-4.42,0 -7.99,3.58 -7.99,8s3.57,8 7.99,8c3.73,0 6.84,-2.55 7.73,-6h-2.08c-0.82,2.33 -3.04,4 -5.65,4 -3.31,0 -6,-2.69 -6,-6s2.69,-6 6,-6c1.66,0 3.14,0.69 4.22,1.78L13,11h7V4l-2.35,2.35z");
        PATHS.put("palette","M12,3c-4.97,0 -9,4.03 -9,9s4.03,9 9,9c0.83,0 1.5,-0.67 1.5,-1.5 0,-0.39 -0.15,-0.74 -0.39,-1.01 -0.23,-0.26 -0.38,-0.61 -0.38,-0.99 0,-0.83 0.67,-1.5 1.5,-1.5H16c2.76,0 5,-2.24 5,-5 0,-4.42 -4.03,-8 -9,-8zM6.5,12c-0.83,0 -1.5,-0.67 -1.5,-1.5S5.67,9 6.5,9 8,9.67 8,10.5 7.33,12 6.5,12zM9.5,8C8.67,8 8,7.33 8,6.5S8.67,5 9.5,5s1.5,0.67 1.5,1.5S10.33,8 9.5,8zM14.5,8c-0.83,0 -1.5,-0.67 -1.5,-1.5S13.67,5 14.5,5s1.5,0.67 1.5,1.5S15.33,8 14.5,8zM17.5,12c-0.83,0 -1.5,-0.67 -1.5,-1.5S16.67,9 17.5,9s1.5,0.67 1.5,1.5 -0.67,1.5 -1.5,1.5z");
        PATHS.put("log","M14,2H6c-1.1,0 -1.99,0.9 -1.99,2L4,20c0,1.1 0.89,2 1.99,2H18c1.1,0 2,-0.9 2,-2V8l-6,-6zM16,18H8v-2h8v2zM16,14H8v-2h8v2zM13,9V3.5L18.5,9H13z");
        PATHS.put("open","M19,19H5V5h7V3H5c-1.11,0 -2,0.9 -2,2v14c0,1.1 0.89,2 2,2h14c1.1,0 2,-0.9 2,-2v-7h-2v7zM14,3v2h3.59l-9.83,9.83 1.41,1.41L19,6.41V10h2V3h-7z");
        PATHS.put("unavailable","M12,2C6.48,2 2,6.48 2,12s4.48,10 10,10 10,-4.48 10,-10S17.52,2 12,2zM4,12c0,-4.42 3.58,-8 8,-8 1.85,0 3.55,0.63 4.9,1.69L5.69,16.9C4.63,15.55 4,13.85 4,12zM12,20c-1.85,0 -3.55,-0.63 -4.9,-1.69L18.31,7.1C19.37,8.45 20,10.15 20,12c0,4.42 -3.58,8 -8,8z");
        PATHS.put("network","M19.35,10.04C18.67,6.59 15.64,4 12,4 9.11,4 6.6,5.64 5.35,8.04 2.34,8.36 0,10.91 0,14c0,3.31 2.69,6 6,6h13c2.76,0 5,-2.24 5,-5 0,-2.64 -2.05,-4.78 -4.65,-4.96z");
        PATHS.put("text","M14,17H4v2h10v-2zM20,9H4v2h16V9zM4,15h16v-2H4v2zM4,5v2h16V5H4z");
        PATHS.put("upload","M9,16h6v-6h4l-7,-7 -7,7h4zM5,18h14v2H5z");
    }
    static final class Icon extends Drawable {
        final Path path;final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);final Matrix matrix=new Matrix();final Path scaled=new Path();
        Icon(String name,int color){path=PathParser.createPathFromPathData(PATHS.getOrDefault(name,PATHS.get("file")));paint.setColor(color);}
        @Override public void draw(Canvas canvas){Rect b=getBounds();matrix.setScale(b.width()/24f,b.height()/24f);matrix.postTranslate(b.left,b.top);path.transform(matrix,scaled);canvas.drawPath(scaled,paint);}
        @Override public void setAlpha(int alpha){paint.setAlpha(alpha);}
        @Override public void setColorFilter(ColorFilter filter){paint.setColorFilter(filter);}
        @Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
        @Override public int getIntrinsicWidth(){return 48;}@Override public int getIntrinsicHeight(){return 48;}
    }
    ImageView icon(String name,int color,int size){ImageView v=new ImageView(a);v.setImageDrawable(new Icon(name,color));v.setLayoutParams(new LinearLayout.LayoutParams(dp(size),dp(size)));return v;}
    /** A white icon on a small coloured rounded tile, like Settings rows. */
    View tile(String name,int color){FrameLayout f=new FrameLayout(a);f.setBackground(round(color,8));ImageView i=icon(name,0xffffffff,20);FrameLayout.LayoutParams p=new FrameLayout.LayoutParams(dp(20),dp(20),Gravity.CENTER);f.addView(i,p);f.setLayoutParams(new LinearLayout.LayoutParams(dp(32),dp(32)));return f;}

    // ---------- shapes and text ----------
    GradientDrawable round(int color,float radius){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));return d;}
    /** Ripple on touch, accent tint when focused with a remote. */
    Drawable pressable(int color,float radius){
        StateListDrawable states=new StateListDrawable();GradientDrawable focused=round(blend(color,accent,dark?0.22f:0.14f),radius);if(tv)focused.setStroke(dp(2),accent);
        states.addState(new int[]{android.R.attr.state_focused},focused);states.addState(new int[]{},round(color,radius));
        return new RippleDrawable(ColorStateList.valueOf(dark?0x33ffffff:0x22000000),states,round(0xffffffff,radius));
    }
    static int blend(int a,int b,float f){int r=(int)(Color.red(a)*(1-f)+Color.red(b)*f),g=(int)(Color.green(a)*(1-f)+Color.green(b)*f),bl=(int)(Color.blue(a)*(1-f)+Color.blue(b)*f);return Color.argb(Color.alpha(a),r,g,bl);}
    TextView text(String s,float size,int color,boolean bold){TextView v=new TextView(a);v.setText(s);v.setTextSize(size);v.setTextColor(color);if(bold)v.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));v.setIncludeFontPadding(true);return v;}
    TextView largeTitle(String s){TextView v=text(s,tv?28:30,text,true);v.setTypeface(Typeface.create("sans-serif",Typeface.BOLD));v.setPadding(dp(4),dp(4),0,dp(12));v.setSingleLine(true);v.setEllipsize(TextUtils.TruncateAt.END);return v;}
    LinearLayout column(){LinearLayout v=new LinearLayout(a);v.setOrientation(LinearLayout.VERTICAL);return v;}
    LinearLayout rowLayout(){LinearLayout v=new LinearLayout(a);v.setOrientation(LinearLayout.HORIZONTAL);v.setGravity(Gravity.CENTER_VERTICAL);return v;}

    /** Back link above a title, top left as on every platform. */
    View backLink(String title,Runnable action){
        LinearLayout v=rowLayout();v.setPadding(dp(2),dp(6),dp(12),dp(6));v.addView(icon("back",accent,20));TextView label=text(title,16,accent,true);label.setPadding(dp(6),0,0,0);v.addView(label);
        v.setBackground(pressable(0x00000000,10));v.setFocusable(true);v.setClickable(true);v.setOnClickListener(x->action.run());v.setContentDescription(title);
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-2,-2);p.setMargins(0,0,0,dp(2));v.setLayoutParams(p);return v;
    }

    /** One row: icon tile, title, optional subtitle, optional value, chevron. */
    LinearLayout row(String iconName,int iconColor,String title,String subtitle,String value,boolean chevron,Runnable action){
        LinearLayout r=rowLayout();r.setMinimumHeight(dp(tv?60:56));r.setPadding(dp(14),dp(8),dp(12),dp(8));
        if(iconName!=null){View tile=tile(iconName,iconColor);LinearLayout.LayoutParams p=(LinearLayout.LayoutParams)tile.getLayoutParams();p.setMargins(0,0,dp(14),0);r.addView(tile);}
        LinearLayout texts=column();TextView name=text(title,tv?17:16,iconName==null&&iconColor==danger?danger:text,false);name.setMaxLines(2);name.setEllipsize(TextUtils.TruncateAt.MIDDLE);texts.addView(name);
        if(subtitle!=null&&!subtitle.isEmpty()){TextView sub=text(subtitle,13,secondary,false);sub.setMaxLines(2);sub.setEllipsize(TextUtils.TruncateAt.END);texts.addView(sub);}
        r.addView(texts,new LinearLayout.LayoutParams(0,-2,1));
        if(value!=null&&!value.isEmpty()){boolean actionValue=!chevron&&action!=null;TextView v=text(value,15,actionValue?accent:secondary,actionValue);v.setPadding(dp(8),0,dp(4),0);v.setSingleLine(true);r.addView(v);}
        if(chevron){ImageView c=icon("chevron",tertiary,20);r.addView(c);}
        if(action!=null){r.setBackground(pressable(0x00000000,0));r.setFocusable(true);r.setClickable(true);r.setOnClickListener(x->action.run());}
        r.setContentDescription(title+(subtitle==null?"":", "+subtitle));
        return r;
    }
    /** A trailing ⋮ button with a native menu. */
    ImageButton moreButton(String description,View.OnClickListener listener){
        ImageButton b=new ImageButton(a);b.setImageDrawable(new Icon("more",secondary));b.setBackground(pressable(0x00000000,20));b.setPadding(dp(10),dp(10),dp(10),dp(10));b.setScaleType(ImageView.ScaleType.FIT_CENTER);
        b.setContentDescription(description);b.setOnClickListener(listener);b.setLayoutParams(new LinearLayout.LayoutParams(dp(44),dp(44)));return b;
    }
    /** Section: small header, rounded card of rows with inset dividers, optional footer. */
    LinearLayout section(String header,java.util.List<View> rows,String footer){
        LinearLayout block=column();
        if(header!=null&&!header.isEmpty()){TextView h=text(header.toUpperCase(java.util.Locale.getDefault()),12.5f,secondary,true);h.setLetterSpacing(0.04f);h.setPadding(dp(16),dp(4),dp(16),dp(6));block.addView(h);}
        if(!rows.isEmpty()){LinearLayout card=column();card.setBackground(round(surface,16));card.setClipToOutline(true);
            for(int i=0;i<rows.size();i++){if(i>0){View line=new View(a);line.setBackgroundColor(separator);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,Math.max(1,dp(0.6f)));p.setMargins(dp(60),0,0,0);card.addView(line,p);}card.addView(rows.get(i),new LinearLayout.LayoutParams(-1,-2));}
            block.addView(card);}
        if(footer!=null&&!footer.isEmpty()){TextView f=text(footer,13,secondary,false);f.setPadding(dp(16),dp(6),dp(16),0);block.addView(f);}
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,0,0,dp(22));block.setLayoutParams(p);return block;
    }
    Button pill(String title,int color,int textColor,Runnable action){
        Button b=new Button(a);b.setText(title);b.setAllCaps(false);b.setTextSize(15);b.setTextColor(textColor);b.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));
        b.setBackground(pressable(color,14));b.setMinHeight(dp(48));b.setPadding(dp(16),dp(8),dp(16),dp(8));b.setStateListAnimator(null);b.setOnClickListener(v->action.run());return b;
    }
    /** A sheet that rises from the bottom (phone) or a centred card (TV). */
    Dialog sheet(View content,boolean cancelable){
        Dialog d=new Dialog(a);d.requestWindowFeature(Window.FEATURE_NO_TITLE);
        LinearLayout box=column();box.setPadding(dp(22),dp(10),dp(22),dp(22));
        GradientDrawable shape=new GradientDrawable();shape.setColor(bg);float r=dp(24);shape.setCornerRadii(tv?new float[]{r,r,r,r,r,r,r,r}:new float[]{r,r,r,r,0,0,0,0});box.setBackground(shape);
        if(!tv){View grabber=new View(a);grabber.setBackground(round(tertiary,3));LinearLayout.LayoutParams g=new LinearLayout.LayoutParams(dp(40),dp(5));g.gravity=Gravity.CENTER_HORIZONTAL;g.setMargins(0,0,0,dp(14));box.addView(grabber,g);}
        box.addView(content);d.setContentView(box);d.setCancelable(cancelable);
        Window w=d.getWindow();if(w!=null){w.setBackgroundDrawable(new ColorDrawable(0));w.setLayout(tv?dp(560):-1,-2);w.setGravity(tv?Gravity.CENTER:Gravity.BOTTOM);w.setDimAmount(0.45f);}
        return d;
    }
}
