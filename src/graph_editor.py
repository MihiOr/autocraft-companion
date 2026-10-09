"""Tk editor for the two curves embedded in the custom motor policy."""
import copy
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import control_graphs as curves


class GraphPage(ttk.Frame):
    def __init__(self, parent, editor, key):
        super().__init__(parent)
        self.editor,self.key=editor,key
        self.selected=None;self.drag=None;self.bounds=None;self.hits=[]
        self.manual=tk.BooleanVar()
        self.raw=tk.BooleanVar()
        tools=ttk.Frame(self);tools.pack(fill='x',padx=8,pady=6)
        ttk.Checkbutton(tools,text='Edit Bézier handles / show control polygon',variable=self.manual,
                        command=self.toggle_manual).pack(side='left')
        if key=='steering':
            ttk.Checkbutton(tools,text='Original measurements',variable=self.raw,
                            command=self.draw).pack(side='left',padx=10)
        ttk.Button(tools,text='Fit graph',command=self.fit).pack(side='right')
        ttk.Button(tools,text='Automatic curve',command=self.reset_auto).pack(side='right',padx=8)
        self.canvas=tk.Canvas(self,bg='#151c26',highlightthickness=0,takefocus=True)
        self.canvas.pack(fill='both',expand=True,padx=8)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<Button-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Double-Button-1>',self.add)
        self.canvas.bind('<Delete>',lambda e:self.delete())
        self.canvas.bind('<MouseWheel>',self.zoom)
        bottom=ttk.Frame(self);bottom.pack(fill='x',padx=8,pady=8)
        self.x=tk.StringVar();self.y=tk.StringVar();self.info=tk.StringVar()
        for label,var in (('X',self.x),('Y',self.y)):
            ttk.Label(bottom,text=label).pack(side='left',padx=(0,4))
            entry=ttk.Entry(bottom,textvariable=var,width=15);entry.pack(side='left',padx=(0,12))
            entry.bind('<Return>',lambda e:self.edit_point())
        ttk.Button(bottom,text='Update point',command=self.edit_point).pack(side='left')
        ttk.Button(bottom,text='Delete point',command=self.delete).pack(side='left',padx=8)
        ttk.Label(bottom,textvariable=self.info).pack(side='right')
        self.refresh()

    @property
    def graph(self):return self.editor.profile['graphs'][self.key]

    def refresh(self):
        self.selected=None;self.manual.set(self.graph['mode']=='manual');self.bounds=None
        self.selection();self.fit()

    def fit(self):
        coords=[(p['x'],p['y']) for p in self.graph['points']]
        if self.manual.get():
            coords += [h for p in self.graph['points'] for k in ('in','out') if (h:=p.get(k))]
        xmin,xmax=min(x for x,y in coords),max(x for x,y in coords)
        ymin,ymax=min(y for x,y in coords),max(y for x,y in coords)
        dx=max(xmax-xmin,1);dy=max(ymax-ymin,1)
        self.bounds=(xmin-.07*dx,xmax+.07*dx,ymin-.12*dy,ymax+.12*dy)
        self.draw()

    def pixel(self,x,y):
        xmin,xmax,ymin,ymax=self.bounds
        w,h=max(240,self.canvas.winfo_width()),max(200,self.canvas.winfo_height())
        return 75+(x-xmin)/(xmax-xmin)*(w-110),h-55-(y-ymin)/(ymax-ymin)*(h-95)

    def world(self,x,y):
        xmin,xmax,ymin,ymax=self.bounds
        w,h=max(240,self.canvas.winfo_width()),max(200,self.canvas.winfo_height())
        return xmin+(x-75)/(w-110)*(xmax-xmin),ymin+(h-55-y)/(h-95)*(ymax-ymin)

    def draw(self):
        if self.bounds is None:return
        c=self.canvas;c.delete('all');self.hits=[]
        w,h=max(240,c.winfo_width()),max(200,c.winfo_height())
        xmin,xmax,ymin,ymax=self.bounds
        for i in range(7):
            x=xmin+(xmax-xmin)*i/6;y=ymin+(ymax-ymin)*i/6
            px,_=self.pixel(x,0);_,py=self.pixel(0,y)
            c.create_line(px,30,px,h-55,fill='#2c3948')
            c.create_line(75,py,w-35,py,fill='#2c3948')
            c.create_text(px,h-38,text=f'{x:.4g}',fill='#c1cbd7')
            c.create_text(67,py,text=f'{y:.4g}',anchor='e',fill='#c1cbd7')
        for axis in (0,1):
            if axis==0 and xmin<=0<=xmax:
                px,_=self.pixel(0,0);c.create_line(px,30,px,h-55,fill='#697b8e')
            if axis==1 and ymin<=0<=ymax:
                _,py=self.pixel(0,0);c.create_line(75,py,w-35,py,fill='#697b8e')
        c.create_text(w/2,14,text=curves.LABELS[self.key][2],fill='#dbe6f1')
        c.create_text(w/2,h-13,text=curves.LABELS[self.key][1],fill='#dbe6f1')
        for seg in curves.segments(self.graph):
            pixels=[v for i in range(21) for v in self.pixel(*curves.bezier(seg,i/20))]
            c.create_line(*pixels,fill='#ffa64d',width=2,tags='curve')
        if self.raw.get():
            for pt in self.graph['points']:
                if 'measured_y' in pt:
                    x,y=self.pixel(pt.get('measured_x',pt['x']),pt['measured_y'])
                    c.create_oval(x-2,y-2,x+2,y+2,fill='#728192',outline='',tags='measured')
        for i,pt in enumerate(self.graph['points']):
            x,y=self.pixel(pt['x'],pt['y']);r=5 if i==self.selected else 3
            c.create_oval(x-r,y-r,x+r,y+r,fill='#ffffff' if i==self.selected else '#5dd9fa',outline='',tags='point')
            self.hits.append((x,y,'point',i,None))
        if self.manual.get() and self.selected is not None:
            segs=curves.segments(self.graph)
            for j in (self.selected-1,self.selected):
                if 0<=j<len(segs):
                    pixels=[v for xy in segs[j] for v in self.pixel(*xy)]
                    c.create_line(*pixels,fill='#9b80c0',dash=(4,4),tags='polygon')
            for kind,j,slot in (('in',self.selected-1,2),('out',self.selected,1)):
                if 0<=j<len(segs):
                    x,y=self.pixel(*segs[j][slot])
                    c.create_rectangle(x-5,y-5,x+5,y+5,fill='#c59bff',outline='#ffffff',tags='handle')
                    self.hits.insert(0,(x,y,'handle',self.selected,kind))
        self.info.set(f"{len(self.graph['points'])} points · {self.graph['mode']}")

    def closest(self,e):
        choices=[(math.hypot(x-e.x,y-e.y),kind,i,handle) for x,y,kind,i,handle in self.hits]
        choices.sort(key=lambda p:p[0])
        return choices[0] if choices and choices[0][0]<=9 else None

    def selection(self):
        if self.selected is None:
            self.x.set('');self.y.set('')
        else:
            p=self.graph['points'][self.selected]
            self.x.set(f"{p['x']:.10g}");self.y.set(f"{p['y']:.10g}")
        self.entry_pair=(self.x.get(),self.y.get())

    def commit_pending(self):
        if self.selected is None or (self.x.get(),self.y.get())==self.entry_pair:return
        x,y=curves.number(self.x.get()),curves.number(self.y.get())
        self.move_point(self.selected,x,y);self.selection();self.draw()

    def press(self,e):
        try:self.commit_pending()
        except ValueError as exc:
            messagebox.showerror('Point value',str(exc),parent=self);return
        self.canvas.focus_set();hit=self.closest(e)
        if hit:
            _,kind,i,handle=hit;self.selected=i;self.drag=(kind,handle)
        else:self.selected=None;self.drag=None
        self.selection();self.draw()

    def clamp_handles(self):
        pts=self.graph['points']
        for i,pt in enumerate(pts):
            for kind,lo,hi in (('in',pts[max(0,i-1)]['x'],pt['x']),
                               ('out',pt['x'],pts[min(len(pts)-1,i+1)]['x'])):
                if kind in pt:pt[kind][0]=max(lo,min(hi,pt[kind][0]))

    def move_point(self,i,x,y):
        pts=self.graph['points'];pt=pts[i]
        if i:x=max(x,pts[i-1]['x']+1e-5)
        if i<len(pts)-1:x=min(x,pts[i+1]['x']-1e-5)
        dx,dy=x-pt['x'],y-pt['y'];pt['x'],pt['y']=x,y
        for kind in ('in','out'):
            if kind in pt:pt[kind]=[pt[kind][0]+dx,pt[kind][1]+dy]
        self.clamp_handles()

    def motion(self,e):
        if self.drag is None or self.selected is None:return
        x,y=self.world(e.x,e.y);kind,handle=self.drag
        if kind=='point':self.move_point(self.selected,x,y)
        else:
            self.graph['points'][self.selected][handle]=[x,y];self.clamp_handles()
        self.selection();self.draw()

    def release(self,e):
        if self.drag:self.editor.changed()
        self.drag=None

    def add(self,e):
        if self.closest(e):return
        x,y=self.world(e.x,e.y)
        if any(abs(x-p['x'])<1e-5 for p in self.graph['points']):return
        pt=dict(x=x,y=y);self.graph['points'].append(pt)
        self.graph['points'].sort(key=lambda p:p['x']);self.selected=self.graph['points'].index(pt)
        self.clamp_handles();self.selection();self.draw();self.editor.changed()

    def delete(self):
        if self.selected is None:return
        if len(self.graph['points'])<=2:
            self.editor.status.set('Keep at least two points in each graph.');return
        self.graph['points'].pop(self.selected);self.selected=None;self.clamp_handles()
        self.selection();self.draw();self.editor.changed()

    def edit_point(self):
        if self.selected is None:return
        try:
            x,y=curves.number(self.x.get()),curves.number(self.y.get())
            self.move_point(self.selected,x,y);self.selection();self.draw();self.editor.changed()
        except ValueError as exc:messagebox.showerror('Point value',str(exc),parent=self)

    def toggle_manual(self):
        if self.manual.get() and self.graph['mode']=='auto':
            segs=curves.segments(self.graph)
            self.graph['mode']='manual'
            for i,seg in enumerate(segs):
                self.graph['points'][i]['out']=list(seg[1])
                self.graph['points'][i+1]['in']=list(seg[2])
        # Hiding handles must not discard the manually edited curve.
        self.draw();self.editor.changed()

    def reset_auto(self):
        self.graph['mode']='auto';self.manual.set(False)
        for pt in self.graph['points']:
            pt.pop('in',None);pt.pop('out',None)
        self.draw();self.editor.changed()

    def zoom(self,e):
        x,y=self.world(e.x,e.y);factor=.8 if e.delta>0 else 1.25
        a,b,c,d=self.bounds
        self.bounds=(x+(a-x)*factor,x+(b-x)*factor,y+(c-y)*factor,y+(d-y)*factor)
        self.draw()


class GraphEditor(tk.Toplevel):
    def __init__(self,parent):
        super().__init__(parent)
        self.title('MiTVS · Motor control graphs');self.geometry('1100x740');self.minsize(880,590)
        self.profile=curves.ensure_files();draft=curves.FOLDER/'_draft.json'
        if draft.exists():
            try:self.profile=curves.load(draft)
            except ValueError:pass
        top=ttk.Frame(self,padding=10);top.pack(fill='x')
        self.file=tk.StringVar(value=self.profile.get('name','Measured default.json'))
        self.files=ttk.Combobox(top,textvariable=self.file,width=28,state='readonly');self.files.pack(side='left')
        ttk.Button(top,text='Load & use',command=self.load_selected).pack(side='left',padx=6)
        ttk.Button(top,text='Browse…',command=self.browse).pack(side='left')
        ttk.Button(top,text='Save & use…',command=self.save_use).pack(side='right')
        ttk.Button(top,text='Apply',command=self.apply).pack(side='right',padx=8)
        self.status=tk.StringVar(value='Double-click to add · drag to move · select + Delete to remove · mouse wheel to zoom')
        ttk.Label(self,textvariable=self.status,wraplength=1040).pack(fill='x',padx=12,pady=(0,6))
        meta=ttk.Frame(self);meta.pack(fill='x',padx=12,pady=(0,5))
        self.reference=tk.StringVar(value=str(self.profile['reference_speed_kmh']))
        ttk.Label(meta,text='Steering graph reference speed (km/h):').pack(side='left')
        ttk.Entry(meta,textvariable=self.reference,width=9).pack(side='left',padx=8)
        ttk.Label(meta,text='Curves are sampled into your Lua on Apply; reapply/export to update the car.').pack(side='left')
        tabs=ttk.Notebook(self);tabs.pack(fill='both',expand=True,padx=4,pady=4)
        self.pages={}
        for key in curves.LABELS:
            page=GraphPage(tabs,self,key);tabs.add(page,text=curves.LABELS[key][0]);self.pages[key]=page
        self.reference.trace_add('write',lambda *_:self.changed())
        self.refresh_files()
        self.protocol('WM_DELETE_WINDOW',self.close)

    def refresh_files(self):
        self.files.configure(values=sorted(p.name for p in curves.FOLDER.glob('*.json') if not p.name.startswith('_')))

    def changed(self):
        self.status.set('Draft saved. Apply or Save & use to update motor control.')
        try:
            self.profile=self.candidate(commit_edits=False)
            curves.save(curves.FOLDER/'_draft.json',self.profile)
        except (ValueError,OSError) as exc:self.status.set(str(exc))

    def candidate(self,commit_edits=True):
        if commit_edits:
            for page in self.pages.values():page.commit_pending()
        p=copy.deepcopy(self.profile);p['reference_speed_kmh']=curves.number(self.reference.get())
        return curves.validate(p)

    def close(self):
        try:curves.save(curves.FOLDER/'_draft.json',self.candidate())
        except (ValueError,OSError) as exc:
            messagebox.showerror('Save draft',str(exc),parent=self);return
        self.destroy()

    def apply(self):
        try:
            p=self.candidate();counts=curves.apply(p);self.profile=p
            curves.save(curves.FOLDER/'_draft.json',p)
            self.status.set(f'Applied and Lua checked: {counts[0]} steering / {counts[1]} correction samples. Reapply/export to update the car.')
            return True
        except (ValueError,OSError) as exc:
            messagebox.showerror('Graphs',str(exc),parent=self);return False

    def save_use(self):
        path=filedialog.asksaveasfilename(parent=self,initialdir=curves.FOLDER,
                 initialfile=self.file.get(),defaultextension='.json',filetypes=[('Motor graph profiles','*.json')])
        if not path:return
        try:
            p=self.candidate();p['name']=curves.Path(path).name
            curves.apply(p,save_path=path);curves.save(curves.FOLDER/'_draft.json',p)
            self.profile=p;self.file.set(p['name']);self.refresh_files()
            self.status.set('Both graphs saved and applied. Reapply/export to update the car.')
        except (ValueError,OSError) as exc:messagebox.showerror('Save graphs',str(exc),parent=self)

    def load_path(self,path):
        try:
            p=curves.load(path);p['name']=curves.Path(path).name;curves.apply(p)
            self.profile=p;curves.save(curves.FOLDER/'_draft.json',p)
            self.reference.set(str(p['reference_speed_kmh']));self.file.set(p['name'])
            for page in self.pages.values():page.refresh()
            self.status.set('Both graphs loaded and applied. Reapply/export to update the car.')
        except (ValueError,OSError) as exc:messagebox.showerror('Load graphs',str(exc),parent=self)

    def load_selected(self):
        name=curves.Path(self.file.get()).name
        if name.startswith('_'):return
        self.load_path(curves.FOLDER/name)

    def browse(self):
        path=filedialog.askopenfilename(parent=self,initialdir=curves.FOLDER,filetypes=[('Motor graph profiles','*.json')])
        if path:self.load_path(path)
