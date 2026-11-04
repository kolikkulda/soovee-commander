// Progress of copies, moves and archives: a small sheet with a bar, sizes, speed and time left.
// It can be hidden; the operation continues and stays visible in Transfers.
// Included inside SooveeViewController.
#if !TARGET_OS_TV

- (UILabel *)progressLabel:(UIFontTextStyle)style weight:(UIFontWeight)weight color:(UIColor *)color {
    UILabel *label=[self textLabel:@" " style:style weight:weight color:color];label.numberOfLines=1;return label;
}
- (void)startOperation:(NSString *)title route:(NSString *)route call:(NSString *)name args:(NSArray *)args done:(void (^)(NSDictionary *))done {
    UIViewController *sheet=[UIViewController new];sheet.view.backgroundColor=Background();
    UIStackView *stack=[UIStackView new];stack.axis=UILayoutConstraintAxisVertical;stack.spacing=10;stack.translatesAutoresizingMaskIntoConstraints=NO;[sheet.view addSubview:stack];
    [NSLayoutConstraint activateConstraints:@[[stack.leadingAnchor constraintEqualToAnchor:sheet.view.layoutMarginsGuide.leadingAnchor constant:8],[stack.trailingAnchor constraintEqualToAnchor:sheet.view.layoutMarginsGuide.trailingAnchor constant:-8],[stack.topAnchor constraintEqualToAnchor:sheet.view.topAnchor constant:28]]];
    UILabel *heading=[self textLabel:title style:UIFontTextStyleTitle2 weight:UIFontWeightBold color:UIColor.labelColor];[stack addArrangedSubview:heading];
    UILabel *where=[self progressLabel:UIFontTextStyleSubheadline weight:UIFontWeightRegular color:UIColor.secondaryLabelColor];where.text=route;where.lineBreakMode=NSLineBreakByTruncatingMiddle;[stack addArrangedSubview:where];[stack setCustomSpacing:18 afterView:where];
    self.progressName=[self progressLabel:UIFontTextStyleHeadline weight:UIFontWeightSemibold color:UIColor.labelColor];self.progressName.lineBreakMode=NSLineBreakByTruncatingMiddle;self.progressName.text=T(@"Preparing files…");[stack addArrangedSubview:self.progressName];
    self.progressBar=[[UIProgressView alloc]initWithProgressViewStyle:UIProgressViewStyleDefault];self.progressBar.progressTintColor=Accent();self.progressBar.trackTintColor=[UIColor.secondaryLabelColor colorWithAlphaComponent:.2];
    [self.progressBar.heightAnchor constraintEqualToConstant:8].active=YES;self.progressBar.layer.cornerRadius=4;self.progressBar.clipsToBounds=YES;[stack addArrangedSubview:self.progressBar];
    UIStackView *numbers=[UIStackView new];numbers.axis=UILayoutConstraintAxisHorizontal;
    self.progressBytes=[self progressLabel:UIFontTextStyleSubheadline weight:UIFontWeightMedium color:UIColor.labelColor];self.progressPercent=[self progressLabel:UIFontTextStyleSubheadline weight:UIFontWeightSemibold color:Accent()];self.progressPercent.textAlignment=NSTextAlignmentRight;
    [numbers addArrangedSubview:self.progressBytes];[numbers addArrangedSubview:self.progressPercent];[stack addArrangedSubview:numbers];
    self.progressSpeed=[self progressLabel:UIFontTextStyleFootnote weight:UIFontWeightRegular color:UIColor.secondaryLabelColor];[stack addArrangedSubview:self.progressSpeed];[stack setCustomSpacing:22 afterView:self.progressSpeed];
    UIButton *hide=[UIButton buttonWithType:UIButtonTypeSystem];UIButtonConfiguration *hideStyle=[UIButtonConfiguration tintedButtonConfiguration];hideStyle.title=T(@"Hide");hideStyle.baseForegroundColor=Accent();hideStyle.baseBackgroundColor=Accent();hideStyle.cornerStyle=UIButtonConfigurationCornerStyleLarge;hide.configuration=hideStyle;
    __weak UIViewController *weakSheet=sheet;[hide addAction:[UIAction actionWithHandler:^(UIAction *a){[weakSheet dismissViewControllerAnimated:YES completion:nil];}] forControlEvents:UIControlEventPrimaryActionTriggered];
    UIButton *stop=[UIButton buttonWithType:UIButtonTypeSystem];UIButtonConfiguration *stopStyle=[UIButtonConfiguration tintedButtonConfiguration];stopStyle.title=T(@"Stop");stopStyle.baseForegroundColor=UIColor.systemRedColor;stopStyle.baseBackgroundColor=UIColor.systemRedColor;stopStyle.cornerStyle=UIButtonConfigurationCornerStyleLarge;stop.configuration=stopStyle;
    [stop addAction:[UIAction actionWithHandler:^(UIAction *a){stop.enabled=NO;self.progressStopped=YES;self.progressName.text=T(@"Stopping…");dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{CoreCall(@"cancel_operation",@[],NO);});}] forControlEvents:UIControlEventPrimaryActionTriggered];
    UIStackView *buttons=[[UIStackView alloc]initWithArrangedSubviews:@[hide,stop]];buttons.distribution=UIStackViewDistributionFillEqually;buttons.spacing=12;[buttons.heightAnchor constraintEqualToConstant:50].active=YES;[stack addArrangedSubview:buttons];
    UILabel *note=[self textLabel:T(@"Hiding keeps it running; see Transfers.") style:UIFontTextStyleFootnote weight:UIFontWeightRegular color:UIColor.tertiaryLabelColor];note.textAlignment=NSTextAlignmentCenter;[stack addArrangedSubview:note];
    sheet.modalPresentationStyle=UIModalPresentationPageSheet;sheet.overrideUserInterfaceStyle=self.overrideUserInterfaceStyle;
    UISheetPresentationController *presentation=sheet.sheetPresentationController;
    presentation.detents=@[[UISheetPresentationControllerDetent customDetentWithIdentifier:@"progress" resolver:^CGFloat(id<UISheetPresentationControllerDetentResolutionContext> context){return 360;}]];
    presentation.prefersGrabberVisible=YES;presentation.preferredCornerRadius=24;
    self.progressSheet=sheet;self.progressStopped=NO;self.progressStarted=[NSDate date];self.progressRoute=route;
    [self.progressBar setProgress:0 animated:NO];self.progressBytes.text=@" ";self.progressPercent.text=@"";self.progressSpeed.text=T(@"Calculating time left…");
    [self presentViewController:sheet animated:YES completion:^{
        [self call:name args:args then:^(NSString *json){
            NSDictionary *value=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];
            UIViewController *open=self.progressSheet;self.progressSheet=nil;
            void (^finish)(void)=^{[self.selection removeAllObjects];self.selectionMode=NO;[self showFiles];if([self twoPanels])[self showOtherFiles];if(done)done([value isKindOfClass:NSDictionary.class]?value:@{});};
            if(open.presentingViewController)[open dismissViewControllerAnimated:YES completion:finish];else finish();}];}];
}
// Called for every progress event from the core.
- (void)updateProgress:(NSDictionary *)state {
    if(!self.progressSheet||![state[@"kind"] isEqual:@"operation"])return;
    double bytes=[state[@"bytes"] doubleValue],total=[state[@"total"] doubleValue];
    NSString *current=[state[@"current"] isKindOfClass:NSString.class]?[state[@"current"] lastPathComponent]:@"";
    if(current.length)self.progressName.text=current;
    NSInteger files=[state[@"total_files"] integerValue]?:[state[@"files"] integerValue],done=[state[@"completed"] integerValue];
    NSString *(^size)(double)=^NSString *(double value){return [NSByteCountFormatter stringFromByteCount:(long long)value countStyle:NSByteCountFormatterCountStyleFile];};
    if(total>0){double fraction=MIN(1,bytes/total);[self.progressBar setProgress:fraction animated:YES];
        self.progressBytes.text=[NSString stringWithFormat:@"%@ %@ %@",size(bytes),T(@"of"),size(total)];self.progressPercent.text=[NSString stringWithFormat:@"%.0f %%",fraction*100];}
    else self.progressBytes.text=size(bytes);
    double elapsed=-[self.progressStarted timeIntervalSinceNow];
    if(elapsed>1&&bytes>0){double speed=bytes/elapsed;NSString *text=[NSString stringWithFormat:@"%@/s",size(speed)];
        if(total>bytes){NSDateComponentsFormatter *left=[NSDateComponentsFormatter new];left.unitsStyle=NSDateComponentsFormatterUnitsStyleAbbreviated;left.maximumUnitCount=2;left.allowedUnits=NSCalendarUnitHour|NSCalendarUnitMinute|NSCalendarUnitSecond;
            NSString *remaining=[left stringFromTimeInterval:MAX(1,(total-bytes)/speed)];if(remaining)text=[NSString stringWithFormat:@"%@ · %@ %@",text,T(@"about"),[NSString stringWithFormat:T(@"%@ left"),remaining]];}
        if(files>1)text=[NSString stringWithFormat:@"%@ · %@",text,[NSString stringWithFormat:T(@"file %ld of %ld"),(long)MIN(done+1,files),(long)files]];
        self.progressSpeed.text=text;}
}
// "Downloads → Target" instead of full sandbox paths.
- (NSString *)routeFrom:(NSString *)source peer:(NSString *)sourcePeer to:(NSString *)folder peer:(NSString *)targetPeer {
    NSString *(^place)(NSString *,NSString *)=^NSString *(NSString *path,NSString *peer){NSString *name=[path isEqual:@"/"]||!path.length?[self deviceName:peer]:path.lastPathComponent;
        return peer.length?[NSString stringWithFormat:@"%@ (%@)",name,[self deviceName:peer]]:name;};
    return [NSString stringWithFormat:@"%@ → %@",place(source,sourcePeer),place(folder,targetPeer)];
}
#endif
