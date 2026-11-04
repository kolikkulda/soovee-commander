package cz.soovee.commander;

import android.view.View;

/** Small vector glyphs remain sharp on phone and TV displays. */
final class FileGlyph extends View {
        final boolean directory;final android.graphics.Paint paint=new android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG);
        FileGlyph(MainActivity host,boolean directory){super(host);this.directory=directory;}
        @Override protected void onDraw(android.graphics.Canvas canvas){super.onDraw(canvas);canvas.save();canvas.scale(getWidth()/32f,getHeight()/32f);
            if(directory){
                paint.setShader(new android.graphics.LinearGradient(3,4,29,29,0xff3a75ff,0xff7656f4,android.graphics.Shader.TileMode.CLAMP));
                canvas.drawRoundRect(3,7,29,28,4,4,paint);canvas.drawRoundRect(3,4,15,14,3,3,paint);
                paint.setShader(new android.graphics.LinearGradient(3,10,29,28,0xff22f1db,0xff05a3ec,android.graphics.Shader.TileMode.CLAMP));canvas.drawRoundRect(2,11,29,28,4,4,paint);
                paint.setShader(null);paint.setColor(0xff9bfff4);canvas.drawRoundRect(5,12,26,14,1,1,paint);
            }else{paint.setShader(new android.graphics.LinearGradient(5,3,27,29,0xffa095ff,0xff547aff,android.graphics.Shader.TileMode.CLAMP));canvas.drawRoundRect(6,3,26,29,4,4,paint);paint.setShader(null);paint.setColor(0xffe0e5ff);canvas.drawRoundRect(10,16,22,18,1,1,paint);canvas.drawRoundRect(10,21,19,23,1,1,paint);}
            canvas.restore();
        }
    }
