// Grid cell for the file list (iPhone/iPad). Included at file scope, before SooveeViewController.
#if !TARGET_OS_TV
@interface SooveeGridCell : UICollectionViewCell
@property(nonatomic,strong) UIImageView *icon;
@property(nonatomic,strong) UILabel *name;
@property(nonatomic,strong) UILabel *detail;
@property(nonatomic,strong) UIImageView *check;
@end

@implementation SooveeGridCell
- (instancetype)initWithFrame:(CGRect)frame {
    self=[super initWithFrame:frame];
    if(!self)return self;
    self.contentView.layer.cornerRadius=12;self.contentView.layer.cornerCurve=kCACornerCurveContinuous;self.contentView.clipsToBounds=YES;
    self.icon=[UIImageView new];self.icon.clipsToBounds=YES;self.icon.layer.cornerRadius=8;self.icon.layer.cornerCurve=kCACornerCurveContinuous;
    self.name=[UILabel new];self.name.font=[UIFont preferredFontForTextStyle:UIFontTextStyleFootnote];self.name.adjustsFontForContentSizeCategory=YES;
    self.name.numberOfLines=2;self.name.lineBreakMode=NSLineBreakByTruncatingMiddle;self.name.textAlignment=NSTextAlignmentCenter;self.name.textColor=UIColor.labelColor;
    self.detail=[UILabel new];self.detail.font=[UIFont preferredFontForTextStyle:UIFontTextStyleCaption2];self.detail.adjustsFontForContentSizeCategory=YES;
    self.detail.textAlignment=NSTextAlignmentCenter;self.detail.textColor=UIColor.secondaryLabelColor;
    UIStackView *stack=[[UIStackView alloc]initWithArrangedSubviews:@[self.icon,self.name,self.detail]];stack.axis=UILayoutConstraintAxisVertical;stack.spacing=6;stack.alignment=UIStackViewAlignmentFill;
    stack.translatesAutoresizingMaskIntoConstraints=NO;[self.contentView addSubview:stack];
    self.check=[[UIImageView alloc]initWithImage:[UIImage systemImageNamed:@"checkmark.circle.fill"]];self.check.translatesAutoresizingMaskIntoConstraints=NO;self.check.hidden=YES;[self.contentView addSubview:self.check];
    [NSLayoutConstraint activateConstraints:@[
        [stack.leadingAnchor constraintEqualToAnchor:self.contentView.leadingAnchor constant:8],[stack.trailingAnchor constraintEqualToAnchor:self.contentView.trailingAnchor constant:-8],
        [stack.topAnchor constraintEqualToAnchor:self.contentView.topAnchor constant:10],[stack.bottomAnchor constraintEqualToAnchor:self.contentView.bottomAnchor constant:-10],
        [self.icon.heightAnchor constraintEqualToConstant:72],
        [self.check.topAnchor constraintEqualToAnchor:self.contentView.topAnchor constant:6],[self.check.trailingAnchor constraintEqualToAnchor:self.contentView.trailingAnchor constant:-6]]];
    self.isAccessibilityElement=YES;self.accessibilityTraits=UIAccessibilityTraitButton;
    return self;
}
@end
#endif
